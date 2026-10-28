"""Public, explicitly allowlisted schemas for authenticated run traces."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TraceSpanView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    parent_span_id: UUID | None
    span_type: Literal[
        "agent_step",
        "tool_call",
        "model_call",
        "policy_check",
    ]
    name: str
    status: str
    started_at: datetime
    ended_at: datetime | None
    duration_ms: int | None = Field(ge=0, default=None)
    safe_summary: str | None


class AuditEventView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    event_type: str
    actor_type: str
    created_at: datetime


class RunTraceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    spans: list[TraceSpanView]
    audit_events: list[AuditEventView]
    spans_truncated: bool
    audit_events_truncated: bool
