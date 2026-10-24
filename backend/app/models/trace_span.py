from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    column,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base


class TraceSpan(Base):
    __tablename__ = "trace_spans"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )

    parent_span_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("trace_spans.id", ondelete="RESTRICT"),
        nullable=True,
    )

    span_type: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    duration_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    safe_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    sanitized_attributes: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )

    __table_args__ = (
        CheckConstraint(
            column("span_type").in_(
                (
                    "agent_step",
                    "tool_call",
                    "model_call",
                    "policy_check",
                )
            )
        ),
        CheckConstraint(column("duration_ms") >= 0),
        Index(
            "ix_trace_spans_run_id_started_at",
            "run_id",
            "started_at",
        ),
    )
