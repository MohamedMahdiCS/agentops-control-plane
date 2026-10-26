from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.runtime.investigation import ToolInvoker
from backend.app.runtime.worker import process_claimed_run
from backend.app.services.run_claims import claim_next_run
from backend.app.simulator.registry import invoke_tool


@dataclass(frozen=True)
class WorkerCycleResult:
    run_id: UUID | None
    finalized: bool


async def run_worker_once(
    session_factory: async_sessionmaker[AsyncSession],
    worker_id: str,
    *,
    run_id: UUID | None = None,
    lease_seconds: int = 60,
    tool_invoker: ToolInvoker = invoke_tool,
) -> WorkerCycleResult:
    """Claim and process at most one eligible agent run.

    A missing job returns without executing tools.
    Claiming and investigation use separate transactions.
    """

    async with session_factory() as session:
        claim = await claim_next_run(
            session,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            run_id=run_id,
        )

    if claim is None:
        return WorkerCycleResult(
            run_id=None,
            finalized=False,
        )

    finalized = await process_claimed_run(
        session_factory,
        claim,
        tool_invoker=tool_invoker,
    )

    return WorkerCycleResult(
        run_id=claim.run_id,
        finalized=finalized,
    )
