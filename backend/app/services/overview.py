"""Read-only control-plane overview built from stored records only."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.benchmark.manifest import BenchmarkManifest, ManifestStore
from backend.app.models.agent_run import AgentRun
from backend.app.models.approval_request import ApprovalRequest
from backend.app.models.audit_event import AuditEvent
from backend.app.models.evaluation_result import EvaluationResult

RUN_STATUSES = (
    "queued",
    "running",
    "awaiting_approval",
    "completed",
    "failed",
    "cancelled",
)
EVENT_LIMIT = 15


@dataclass(frozen=True)
class RecentEvent:
    id: UUID
    event_type: str
    actor_type: str
    run_id: UUID | None
    created_at: datetime


@dataclass(frozen=True)
class Overview:
    generated_at: datetime
    runs_total: int
    runs_by_status: dict[str, int]
    runs_last_24h: int
    runs_hourly: list[int]
    evaluations_total: int
    evaluations_passed: int
    evaluations_failed: int
    evaluations_inconclusive: int
    pending_approvals: int
    latest_benchmark: BenchmarkManifest | None
    recent_events: list[RecentEvent]


async def build_overview(session: AsyncSession, store: ManifestStore) -> Overview:
    now = await session.scalar(select(func.now()))
    if now is None:
        raise RuntimeError("Database clock unavailable")
    window_start = (now - timedelta(hours=23)).replace(
        minute=0, second=0, microsecond=0
    )

    by_status = dict.fromkeys(RUN_STATUSES, 0)
    for status, count in (
        await session.execute(
            select(AgentRun.status, func.count()).group_by(AgentRun.status)
        )
    ).all():
        by_status[status] = count

    hourly = [0] * 24
    bucket = func.date_trunc("hour", AgentRun.created_at)
    for hour, count in (
        await session.execute(
            select(bucket, func.count())
            .where(AgentRun.created_at >= window_start)
            .group_by(bucket)
        )
    ).all():
        index = int((hour - window_start).total_seconds() // 3600)
        if 0 <= index < 24:
            hourly[index] += count

    verdicts = {"passed": 0, "failed": 0, "inconclusive": 0}
    for verdict, count in (
        await session.execute(
            select(EvaluationResult.verdict, func.count()).group_by(
                EvaluationResult.verdict
            )
        )
    ).all():
        if verdict in verdicts:
            verdicts[verdict] = count

    pending = await session.scalar(
        select(func.count()).where(ApprovalRequest.status == "pending")
    )

    events = (
        await session.scalars(
            select(AuditEvent)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(EVENT_LIMIT)
        )
    ).all()

    manifests, _ = store.list()

    return Overview(
        generated_at=now,
        runs_total=sum(by_status.values()),
        runs_by_status=by_status,
        runs_last_24h=sum(hourly),
        runs_hourly=hourly,
        evaluations_total=sum(verdicts.values()),
        evaluations_passed=verdicts["passed"],
        evaluations_failed=verdicts["failed"],
        evaluations_inconclusive=verdicts["inconclusive"],
        pending_approvals=pending or 0,
        latest_benchmark=manifests[0] if manifests else None,
        recent_events=[
            RecentEvent(
                id=event.id,
                event_type=event.event_type,
                actor_type=event.actor_type,
                run_id=event.run_id,
                created_at=event.created_at,
            )
            for event in events
        ],
    )
