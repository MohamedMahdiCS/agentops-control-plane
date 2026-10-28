"""Crash-safe expiration of pending human-approval requests.

This service never dispatches or authorizes tool execution.
It uses the same run-before-approval lock order as operator decisions.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.models.agent_run import AgentRun
from backend.app.models.approval_request import ApprovalRequest
from backend.app.models.audit_event import AuditEvent


async def expire_pending_approvals(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    limit: int = 50,
) -> int:
    """Expire up to `limit` pending approvals using database time.

    Concurrent operator decisions and expiration workers are serialized
    through row locks. Every candidate is revalidated after locking.
    """

    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Expiration batch limit must be between 1 and 100")

    # Discovery is read-only and intentionally separate from mutation.
    async with session_factory() as scan_session:
        candidate_ids = (
            await scan_session.scalars(
                select(ApprovalRequest.id)
                .where(
                    ApprovalRequest.status == "pending",
                    ApprovalRequest.expires_at <= func.clock_timestamp(),
                )
                .order_by(
                    ApprovalRequest.expires_at,
                    ApprovalRequest.id,
                )
                .limit(limit)
            )
        ).all()

    expired_count = 0

    for approval_id in candidate_ids:
        async with session_factory() as session:
            async with session.begin():
                run_id = await session.scalar(
                    select(ApprovalRequest.run_id).where(
                        ApprovalRequest.id == approval_id
                    )
                )

                if run_id is None:
                    continue

                # Consistent lock order: run first, then approval.
                # Skip locked records; another worker can retry later.
                run = await session.scalar(
                    select(AgentRun)
                    .where(AgentRun.id == run_id)
                    .with_for_update(skip_locked=True)
                )

                if run is None:
                    continue

                approval = await session.scalar(
                    select(ApprovalRequest)
                    .where(ApprovalRequest.id == approval_id)
                    .with_for_update(skip_locked=True)
                )

                if approval is None or approval.status != "pending":
                    continue

                if (
                    run.status != "awaiting_approval"
                    or run.pending_approval_id != approval_id
                ):
                    continue

                now = await session.scalar(select(func.clock_timestamp()))

                if now is None:
                    raise RuntimeError("Database clock unavailable")

                if approval.expires_at > now:
                    continue

                approval.status = "expired"
                approval.execution_status = "skipped"

                run.status = "failed"
                run.error_code = "APPROVAL_EXPIRED"
                run.finished_at = now
                run.pending_approval_id = None

                session.add(
                    AuditEvent(
                        run_id=run.id,
                        actor_type="system",
                        actor_identifier="approval-expiration",
                        event_type="approval.expired",
                        resource_type="approval_request",
                        resource_id=str(approval_id),
                        event_payload={
                            "decision": "expired",
                            "executed": False,
                        },
                    )
                )

            # Count only after the transaction commits successfully.
            expired_count += 1

    return expired_count
