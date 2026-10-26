from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.agent_run import AgentRun


@dataclass(frozen=True)
class ClaimedRun:
    run_id: UUID
    agent_id: UUID
    incident_id: str
    execution_mode: str
    agent_config_snapshot: dict[str, object]
    execution_checkpoint: dict[str, object] | None
    active_elapsed_ms: int
    attempt_count: int
    worker_id: str
    lease_generation: int
    lease_expires_at: datetime


async def claim_next_run(
    session: AsyncSession,
    worker_id: str,
    lease_seconds: int = 60,
    run_id: UUID | None = None,
) -> ClaimedRun | None:
    """Atomically claim a queued or abandoned run.

    Each claim obtains a PostgreSQL row lock and advances
    the fencing generation. The caller receives an immutable
    ownership token for subsequent checkpoint operations.
    """
    if not isinstance(worker_id, str) or not 1 <= len(worker_id) <= 128:
        raise ValueError("worker_id must contain 1-128 characters")

    if not worker_id.strip():
        raise ValueError("worker_id cannot be blank")

    if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
        raise ValueError("lease_seconds must be between 1 and 3600")

    async with session.begin():
        statement = select(AgentRun).where(
            or_(
                AgentRun.status == "queued",
                and_(
                    AgentRun.status == "running",
                    AgentRun.lease_expires_at <= func.now(),
                ),
            )
        )

        if run_id is not None:
            statement = statement.where(AgentRun.id == run_id)

        candidate = await session.scalar(
            statement.order_by(AgentRun.created_at, AgentRun.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )

        if candidate is None:
            return None

        database_now = await session.scalar(select(func.now()))
        if database_now is None:
            raise RuntimeError("Unable to obtain database time")

        candidate.status = "running"
        candidate.started_at = candidate.started_at or database_now
        candidate.lease_owner = worker_id
        candidate.lease_expires_at = database_now + timedelta(seconds=lease_seconds)
        candidate.lease_generation += 1
        candidate.attempt_count += 1

        await session.flush()

        return ClaimedRun(
            run_id=candidate.id,
            agent_id=candidate.agent_id,
            incident_id=candidate.incident_id,
            execution_mode=candidate.execution_mode,
            agent_config_snapshot=deepcopy(candidate.agent_config_snapshot),
            execution_checkpoint=deepcopy(candidate.execution_checkpoint),
            active_elapsed_ms=candidate.active_elapsed_ms,
            attempt_count=candidate.attempt_count,
            worker_id=worker_id,
            lease_generation=candidate.lease_generation,
            lease_expires_at=candidate.lease_expires_at,
        )
