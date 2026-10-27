"""Internal approval decisions.

This service does not authenticate operators. Callers MUST obtain
operator identity from a trusted authentication/authorization layer.

Do not expose this service through an unauthenticated HTTP endpoint.
Approval does not authorize or dispatch sensitive tool execution.
"""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.agent_run import AgentRun
from backend.app.models.approval_request import ApprovalRequest
from backend.app.models.audit_event import AuditEvent

OperatorDecision = Literal["approved", "rejected"]


class ApprovalNotFoundError(LookupError):
    pass


class ApprovalConflictError(ValueError):
    pass


@dataclass(frozen=True)
class ApprovalDecisionResult:
    approval_id: UUID
    status: str
    run_status: str
    idempotent: bool


async def decide_pending_approval(
    session: AsyncSession,
    approval_id: UUID,
    *,
    decision: OperatorDecision,
    operator_id: str,
    reason: str,
    idempotency_key: str,
) -> ApprovalDecisionResult:
    """Record a trusted operator decision without executing any tool."""

    if not isinstance(approval_id, UUID):
        raise TypeError("approval_id must be a UUID")

    if decision not in ("approved", "rejected"):
        raise ValueError("Invalid approval decision")

    if (
        not isinstance(operator_id, str)
        or not operator_id.strip()
        or len(operator_id) > 128
    ):
        raise ValueError("Invalid operator identity")

    if not isinstance(reason, str) or not 10 <= len(reason.strip()) <= 1000:
        raise ValueError("A meaningful decision reason is required")

    if (
        not isinstance(idempotency_key, str)
        or not 8 <= len(idempotency_key) <= 128
        or not idempotency_key.isascii()
        or not idempotency_key.isprintable()
    ):
        raise ValueError("Invalid decision idempotency key")

    reason = reason.strip()
    operator_id = operator_id.strip()

    async with session.begin():
        run_id = await session.scalar(
            select(ApprovalRequest.run_id).where(ApprovalRequest.id == approval_id)
        )

        if run_id is None:
            raise ApprovalNotFoundError("Approval request not found")

        # Maintain a consistent lock order: run before approval.
        run = await session.scalar(
            select(AgentRun).where(AgentRun.id == run_id).with_for_update()
        )

        approval = await session.scalar(
            select(ApprovalRequest)
            .where(ApprovalRequest.id == approval_id)
            .with_for_update()
        )

        if run is None or approval is None:
            raise ApprovalNotFoundError("Approval state not found")

        # Retry of precisely the same committed decision is harmless.
        if approval.status != "pending":
            if (
                approval.status == decision
                and approval.decided_by == operator_id
                and approval.decision_reason == reason
                and approval.decision_idempotency_key == idempotency_key
            ):
                return ApprovalDecisionResult(
                    approval_id,
                    approval.status,
                    run.status,
                    True,
                )

            raise ApprovalConflictError("Approval has already been resolved")

        if run.status != "awaiting_approval" or run.pending_approval_id != approval_id:
            raise ApprovalConflictError("Run is not awaiting this approval")

        now = await session.scalar(select(func.clock_timestamp()))

        if now is None:
            raise RuntimeError("Database clock unavailable")

        if approval.expires_at <= now:
            approval.status = "expired"
            approval.execution_status = "skipped"

            run.status = "failed"
            run.error_code = "APPROVAL_EXPIRED"
            run.finished_at = now
            run.pending_approval_id = None

            actor_type = "system"
            actor_identifier = "approval-expiration"
            event_type = "approval.expired"
        else:
            approval.status = decision
            approval.decided_by = operator_id
            approval.decision_reason = reason
            approval.decision_idempotency_key = idempotency_key
            approval.decided_at = now

            actor_type = "operator"
            actor_identifier = operator_id
            event_type = "approval.decided"

            if decision == "rejected":
                approval.execution_status = "skipped"
                run.status = "failed"
                run.error_code = "APPROVAL_REJECTED"
                run.finished_at = now
                run.pending_approval_id = None

            # Approved requests remain awaiting_approval.
            # No sensitive action is dispatched or made executable.

        session.add(
            AuditEvent(
                run_id=run.id,
                actor_type=actor_type,
                actor_identifier=actor_identifier,
                event_type=event_type,
                resource_type="approval_request",
                resource_id=str(approval_id),
                event_payload={
                    "decision": approval.status,
                    "executed": False,
                },
            )
        )

        return ApprovalDecisionResult(
            approval_id,
            approval.status,
            run.status,
            False,
        )
