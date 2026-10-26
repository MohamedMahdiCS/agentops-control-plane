from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

RunStatus = Literal[
    "queued",
    "running",
    "awaiting_approval",
    "completed",
    "failed",
    "cancelled",
]


class AgentRunCreate(BaseModel):
    incident_id: str = Field(
        min_length=5,
        max_length=64,
        pattern=r"^INC-[A-Z0-9]+(?:-[A-Z0-9]+)*$",
    )


class AgentRunAccepted(BaseModel):
    run_id: UUID
    agent_id: UUID
    incident_id: str
    status: RunStatus
    created_at: datetime


class AgentRunResponse(BaseModel):
    run_id: UUID
    agent_id: UUID
    agent_config_version: int
    incident_id: str
    status: RunStatus
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result_summary: str | None
    error: str | None
