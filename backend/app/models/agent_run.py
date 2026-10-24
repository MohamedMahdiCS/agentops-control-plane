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
    UniqueConstraint,
    column,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    agent_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="RESTRICT"),
        nullable=False,
    )

    incident_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        server_default="queued",
    )

    agent_config_version: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_config_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False
    )
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False)

    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_generation: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    execution_checkpoint: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, nullable=True
    )
    checkpoint_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    active_elapsed_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)

    pending_approval_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "approval_requests.id",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        nullable=True,
    )
    benchmark_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=True,
    )

    __table_args__ = (
        Index(
            "ix_agent_runs_status_lease_expires_at",
            "status",
            "lease_expires_at",
        ),
        Index(
            "ix_agent_runs_agent_id_status_created_at",
            "agent_id",
            "status",
            "created_at",
        ),
        UniqueConstraint(
            "agent_id",
            "idempotency_key",
            name="uq_agent_runs_agent_id_idempotency_key",
        ),
        CheckConstraint(column("checkpoint_version") > 0),
        CheckConstraint(column("active_elapsed_ms") >= 0),
        CheckConstraint(column("attempt_count") >= 0),
        CheckConstraint(column("lease_generation") >= 0),
        CheckConstraint(column("agent_config_version") > 0),
        CheckConstraint(column("execution_mode").in_(("deterministic", "model"))),
        CheckConstraint(
            column("status").in_(
                (
                    "queued",
                    "running",
                    "awaiting_approval",
                    "completed",
                    "failed",
                    "cancelled",
                )
            )
        ),
    )
