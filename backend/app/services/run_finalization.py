import re
from typing import Literal

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.agent_run import AgentRun
from backend.app.services.run_claims import ClaimedRun

FinalStatus = Literal["completed", "failed"]


async def finalize_run(
    session: AsyncSession,
    claim: ClaimedRun,
    *,
    status: FinalStatus,
    result_summary: str | None = None,
    error_code: str | None = None,
    active_elapsed_ms: int = 0,
) -> bool:
    """Finalize a run only while its worker lease remains valid.

    Returns False if the run is no longer owned by this worker,
    its lease has expired, or it is already terminal.
    """

    if status not in ("completed", "failed"):
        raise ValueError("Invalid final run status")

    if type(active_elapsed_ms) is not int or active_elapsed_ms < 0:
        raise ValueError("active_elapsed_ms must be nonnegative")

    if result_summary is not None and (
        not isinstance(result_summary, str)
        or not result_summary.strip()
        or len(result_summary) > 2000
    ):
        raise ValueError("Invalid result_summary")

    if status == "completed":
        if result_summary is None:
            raise ValueError("Completed runs require a result summary")
        if error_code is not None:
            raise ValueError("Completed runs cannot have an error code")

    if status == "failed" and (
        not isinstance(error_code, str)
        or re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", error_code) is None
    ):
        raise ValueError("Failed runs require a valid error code")

    async with session.begin():
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
                status=status,
                result_summary=result_summary,
                error_code=error_code,
                finished_at=func.clock_timestamp(),
                lease_owner=None,
                lease_expires_at=None,
                active_elapsed_ms=func.greatest(
                    AgentRun.active_elapsed_ms,
                    active_elapsed_ms,
                ),
            )
            .returning(AgentRun.id)
        )

        updated_id = await session.scalar(statement)

    return updated_id is not None
