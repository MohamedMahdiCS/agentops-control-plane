from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
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


class EvaluationCase(Base):
    __tablename__ = "evaluation_cases"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    scenario_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    category: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    scenario_config: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
    )

    expected_outcome: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
    )

    grader_config: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
    )

    allowed_terminal_statuses: Mapped[list[str]] = mapped_column(
        ARRAY(String(16)),
        nullable=False,
        server_default=text("ARRAY['completed']::varchar(16)[]"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "scenario_key",
            "version",
            name="uq_evaluation_cases_scenario_key_version",
        ),
        CheckConstraint(
            "version > 0",
            name="valid_version",
        ),
        CheckConstraint(
            "category IN ("
            "'baseline', 'operational_failure', "
            "'security', 'integration')",
            name="valid_category",
        ),
        CheckConstraint(
            "cardinality(allowed_terminal_statuses) > 0",
            name="nonempty_terminal_statuses",
        ),
        CheckConstraint(
            "allowed_terminal_statuses <@ "
            "ARRAY['completed', 'failed', 'cancelled']::varchar(16)[]",
            name="valid_terminal_statuses",
        ),
    )
