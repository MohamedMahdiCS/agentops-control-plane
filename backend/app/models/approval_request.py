from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

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

    policy_decision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("policy_decisions.id", ondelete="RESTRICT"),
        nullable=False,
    )

    action: Mapped[str] = mapped_column(String(256), nullable=False)

    resource: Mapped[str] = mapped_column(String(256), nullable=False)

    validated_action_arguments: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False
    )

    action_execution_key: Mapped[str] = mapped_column(String(128), nullable=False)

    risk_level: Mapped[str] = mapped_column(String(24), nullable=False)

    reason: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default="pending",
    )

    execution_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        server_default="not_started",
    )

    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    decision_idempotency_key: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )

    decided_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "action_execution_key",
            name="uq_approval_requests_action_execution_key",
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired')",
            name="valid_status",
        ),
        CheckConstraint(
            "execution_status IN ("
            "'not_started', 'pending_execution', "
            "'executed', 'skipped', 'failed')",
            name="valid_execution_status",
        ),
        CheckConstraint(
            "length(action_execution_key) > 0",
            name="nonempty_action_execution_key",
        ),
        Index(
            "ix_approval_requests_status_expires_at",
            "status",
            "expires_at",
        ),
    )
