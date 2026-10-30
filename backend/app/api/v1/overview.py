"""Operator-authenticated control-plane overview for the console."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.benchmark.manifest import ManifestStore, configured_store
from backend.app.core.dependencies import get_db_session
from backend.app.core.operator_auth import OperatorPrincipal, require_operator
from backend.app.services.overview import build_overview

router = APIRouter(tags=["Overview"])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunActivity(StrictModel):
    total: int
    by_status: dict[str, int]
    last_24h: int
    hourly: list[int]


class EvaluationSummary(StrictModel):
    total: int
    passed: int
    failed: int
    inconclusive: int
    pass_rate: float | None


class BenchmarkGate(StrictModel):
    benchmark_run_id: UUID
    label: str
    gate: Literal["passed", "failed", "blocked", "not_run"]
    created_at: datetime


class OverviewEvent(StrictModel):
    id: UUID
    event_type: str
    actor_type: str
    run_id: UUID | None
    created_at: datetime


class OverviewResponse(StrictModel):
    generated_at: datetime
    runs: RunActivity
    evaluations: EvaluationSummary
    pending_approvals: int
    latest_benchmark: BenchmarkGate | None
    recent_events: list[OverviewEvent]


def get_store(
    principal: Annotated[OperatorPrincipal, Depends(require_operator)],
) -> ManifestStore:
    return configured_store()


@router.get("/overview", response_model=OverviewResponse)
async def get_overview(
    principal: Annotated[OperatorPrincipal, Depends(require_operator)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    store: Annotated[ManifestStore, Depends(get_store)],
) -> OverviewResponse:
    """Aggregate stored runs, evaluations, approvals and audit events."""
    data = await build_overview(session, store)
    benchmark = data.latest_benchmark
    return OverviewResponse(
        generated_at=data.generated_at,
        runs=RunActivity(
            total=data.runs_total,
            by_status=data.runs_by_status,
            last_24h=data.runs_last_24h,
            hourly=data.runs_hourly,
        ),
        evaluations=EvaluationSummary(
            total=data.evaluations_total,
            passed=data.evaluations_passed,
            failed=data.evaluations_failed,
            inconclusive=data.evaluations_inconclusive,
            # Inconclusive results count against the pass rate, never for it.
            pass_rate=round(data.evaluations_passed / data.evaluations_total, 4)
            if data.evaluations_total
            else None,
        ),
        pending_approvals=data.pending_approvals,
        latest_benchmark=BenchmarkGate(
            benchmark_run_id=benchmark.benchmark_run_id,
            label=benchmark.label,
            gate=benchmark.gates.overall.status if benchmark.gates else "not_run",
            created_at=benchmark.created_at,
        )
        if benchmark
        else None,
        recent_events=[OverviewEvent(**vars(event)) for event in data.recent_events],
    )
