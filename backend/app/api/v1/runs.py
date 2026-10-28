from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.dependencies import get_db_session
from backend.app.core.operator_auth import OperatorPrincipal, require_operator
from backend.app.models.audit_event import AuditEvent
from backend.app.models.trace_span import TraceSpan
from backend.app.schemas.agent_run import (
    AgentRunAccepted,
    AgentRunCreate,
    AgentRunResponse,
)
from backend.app.schemas.run_traces import (
    AuditEventView,
    RunTraceResponse,
    TraceSpanView,
)
from backend.app.services.agent_runs import (
    AgentDisabledError,
    AgentNotFoundError,
    IdempotencyConflictError,
    UnsupportedIncidentError,
    create_agent_run,
    get_agent_run,
)

router = APIRouter(tags=["Agent Runs"])


@router.post(
    "/agents/{agent_id}/runs",
    response_model=AgentRunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_agent_run(
    agent_id: UUID,
    payload: AgentRunCreate,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    idempotency_key: Annotated[
        str | None,
        Header(min_length=1, max_length=128),
    ] = None,
) -> AgentRunAccepted:
    try:
        run = await create_agent_run(
            session=session,
            agent_id=agent_id,
            payload=payload,
            idempotency_key=idempotency_key,
        )
    except AgentNotFoundError as exc:
        raise HTTPException(404, "Agent not found") from exc
    except AgentDisabledError as exc:
        raise HTTPException(409, "Agent is disabled") from exc
    except UnsupportedIncidentError as exc:
        raise HTTPException(422, "Unsupported incident identifier") from exc
    except IdempotencyConflictError as exc:
        raise HTTPException(
            409,
            "Idempotency key already used for a different request",
        ) from exc

    response.headers["Location"] = f"/api/v1/runs/{run.id}"

    return AgentRunAccepted(
        run_id=run.id,
        agent_id=run.agent_id,
        incident_id=run.incident_id,
        status=run.status,
        created_at=run.created_at,
    )


@router.get(
    "/runs/{run_id}",
    response_model=AgentRunResponse,
)
async def retrieve_agent_run(
    run_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AgentRunResponse:
    run = await get_agent_run(session, run_id)

    if run is None:
        raise HTTPException(404, "Agent run not found")

    return AgentRunResponse(
        run_id=run.id,
        agent_id=run.agent_id,
        agent_config_version=run.agent_config_version,
        incident_id=run.incident_id,
        status=run.status,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        result_summary=run.result_summary,
        error=run.error_code,
    )


@router.get(
    "/runs/{run_id}/traces",
    response_model=RunTraceResponse,
)
async def retrieve_run_traces(
    run_id: UUID,
    principal: Annotated[OperatorPrincipal, Depends(require_operator)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RunTraceResponse:
    """Return bounded, allowlisted telemetry to an authenticated operator."""

    run = await get_agent_run(session, run_id)

    if run is None:
        raise HTTPException(404, "Agent run not found")

    # The extra row detects truncation without an unbounded query.
    span_rows = (
        await session.scalars(
            select(TraceSpan)
            .where(TraceSpan.run_id == run_id)
            .order_by(TraceSpan.started_at, TraceSpan.id)
            .limit(101)
        )
    ).all()

    audit_rows = (
        await session.scalars(
            select(AuditEvent)
            .where(AuditEvent.run_id == run_id)
            .order_by(AuditEvent.created_at, AuditEvent.id)
            .limit(101)
        )
    ).all()

    spans = [
        TraceSpanView(
            id=span.id,
            parent_span_id=span.parent_span_id,
            span_type=span.span_type,
            name=span.name,
            status=span.status,
            started_at=span.started_at,
            ended_at=span.ended_at,
            duration_ms=span.duration_ms,
            safe_summary=span.safe_summary,
        )
        for span in span_rows[:100]
    ]

    events = [
        AuditEventView(
            id=event.id,
            event_type=event.event_type,
            actor_type=event.actor_type,
            created_at=event.created_at,
        )
        for event in audit_rows[:100]
    ]

    return RunTraceResponse(
        run_id=run.id,
        spans=spans,
        audit_events=events,
        spans_truncated=len(span_rows) > 100,
        audit_events_truncated=len(audit_rows) > 100,
    )
