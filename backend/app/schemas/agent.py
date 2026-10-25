from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    agent_type: Literal["incident_response"]


class AgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    agent_type: Literal["incident_response"]
    status: Literal["active", "disabled"]
    config_version: int
    created_at: datetime


class AgentListResponse(BaseModel):
    agents: list[AgentResponse]
    next_cursor: str | None = None
