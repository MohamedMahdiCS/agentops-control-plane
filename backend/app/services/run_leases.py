from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.agent_run import AgentRun
from backend.app.services.run_claims import ClaimedRun


async def renew_run_lease(
    session: AsyncSession,
    claim: ClaimedRun,
    lease_seconds: int = 180,
) -> bool:
    """Extend a live lease only for its current fenced owner."""

    if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
        raise ValueError("Invalid lease duration")

    async with session.begin():
        database_now = await session.scalar(select(func.clock_timestamp()))

        if database_now is None:
            raise RuntimeError("Database clock unavailable")

        new_expiration = database_now + timedelta(seconds=lease_seconds)

        statement = (
            update(AgentRun)
            .where(
                AgentRun.id == claim.run_id,
                AgentRun.status == "running",
                AgentRun.lease_owner == claim.worker_id,
                AgentRun.lease_generation == claim.lease_generation,
                AgentRun.lease_expires_at > func.clock_timestamp(),
            )
            .values(
                lease_expires_at=func.greatest(
                    AgentRun.lease_expires_at,
                    new_expiration,
                )
            )
            .returning(AgentRun.id)
        )

        updated_id = await session.scalar(statement)

    return updated_id is not None
