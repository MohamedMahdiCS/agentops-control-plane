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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"

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

    evaluation_case_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("evaluation_cases.id", ondelete="RESTRICT"),
        nullable=False,
    )

    case_version: Mapped[int] = mapped_column(Integer, nullable=False)

    grader_version: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default="queued",
    )

    verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)

    score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    passing_threshold: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="80",
    )

    policy_gate_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    criteria_results: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    evidence_span_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)),
        nullable=False,
        server_default=text("'{}'::uuid[]"),
    )

    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)

    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="valid_status",
        ),
        CheckConstraint(
            "verdict IS NULL OR verdict IN ('passed', 'failed', 'inconclusive')",
            name="valid_verdict",
        ),
        CheckConstraint(
            "score BETWEEN 0 AND 100",
            name="valid_score",
        ),
        CheckConstraint(
            "passing_threshold BETWEEN 0 AND 100",
            name="valid_passing_threshold",
        ),
        CheckConstraint(
            "case_version > 0",
            name="valid_case_version",
        ),
        CheckConstraint(
            "grader_version > 0",
            name="valid_grader_version",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="valid_attempt_count",
        ),
        UniqueConstraint(
            "run_id",
            "evaluation_case_id",
            "idempotency_key",
            name="uq_evaluation_results_run_case_idempotency",
        ),
        Index(
            "ix_evaluation_results_run_case_status",
            "run_id",
            "evaluation_case_id",
            "status",
        ),
        Index(
            "ix_evaluation_results_status_lease",
            "status",
            "lease_expires_at",
        ),
    )
