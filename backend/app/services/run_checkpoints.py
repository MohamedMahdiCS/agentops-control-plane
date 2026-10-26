from copy import deepcopy

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.agent_run import AgentRun
from backend.app.services.run_claims import ClaimedRun


async def save_run_checkpoint(
    session: AsyncSession,
    claim: ClaimedRun,
    checkpoint: dict[str, object],
    active_elapsed_ms: int,
) -> bool:
    """Persist progress only while the worker still owns a live lease.

    Returns False when ownership is lost, the lease expires,
    or the run is no longer running.
    """
    if not isinstance(checkpoint, dict):
        raise TypeError("checkpoint must be a dictionary")

    if type(active_elapsed_ms) is not int or active_elapsed_ms < 0:
        raise ValueError("active_elapsed_ms must be nonnegative")

    async with session.begin():
        statement = (
            update(AgentRun)
            .where(
                AgentRun.id == claim.run_id,
                AgentRun.status == "running",
                AgentRun.lease_owner == claim.worker_id,
                AgentRun.lease_generation == claim.lease_generation,
                AgentRun.lease_expires_at > func.clock_timestamp(),
                AgentRun.checkpoint_version == 1,
            )
            .values(
                execution_checkpoint=deepcopy(checkpoint),
                active_elapsed_ms=func.greatest(
                    AgentRun.active_elapsed_ms,
                    active_elapsed_ms,
                ),
            )
            .returning(AgentRun.id)
        )

        updated_id = await session.scalar(statement)

    return updated_id is not None
