from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base


class PolicyDecision(Base):
    __tablename__ = "policy_decisions"

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

    trace_span_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("trace_spans.id", ondelete="RESTRICT"),
        nullable=True,
    )

    policy_rule_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("policy_rules.id", ondelete="RESTRICT"),
        nullable=True,
    )

    policy_rule_version: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    action: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
    )

    resource: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
    )

    decision: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
    )

    reason_code: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
    )

    reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    executed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "decision IN ('allow', 'require_approval', 'deny')",
            name="valid_decision",
        ),
        CheckConstraint(
            "(policy_rule_id IS NULL AND policy_rule_version IS NULL)"
            " OR "
            "(policy_rule_id IS NOT NULL AND policy_rule_version > 0)",
            name="rule_version_consistency",
        ),
        Index(
            "ix_policy_decisions_run_id_created_at",
            "run_id",
            "created_at",
        ),
    )
