from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.dependencies import get_db_session
from backend.app.schemas.agent_run import (
    AgentRunAccepted,
    AgentRunCreate,
    AgentRunResponse,
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
