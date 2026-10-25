from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.dependencies import get_db_session
from backend.app.schemas.agent import AgentCreate, AgentListResponse, AgentResponse
from backend.app.services.agent_registry import (
    list_agents as fetch_agents,
)
from backend.app.services.agent_registry import (
    register_agent,
)

router = APIRouter(prefix="/agents", tags=["Agents"])


@router.post(
    "",
    response_model=AgentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_agent(
    payload: AgentCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AgentResponse:
    agent = await register_agent(session, payload)
    return AgentResponse.model_validate(agent)


@router.get("", response_model=AgentListResponse)
async def get_agents(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=256)] = None,
) -> AgentListResponse:
    try:
        agents, next_cursor = await fetch_agents(session, limit=limit, cursor=cursor)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid agent pagination cursor",
        ) from exc

    return AgentListResponse(
        agents=[AgentResponse.model_validate(agent) for agent in agents],
        next_cursor=next_cursor,
    )
