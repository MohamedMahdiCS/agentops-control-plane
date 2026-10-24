from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base


class PolicyRule(Base):
    __tablename__ = "policy_rules"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    rule_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    action_pattern: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
    )

    resource_pattern: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
    )

    effect: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
    )

    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    rule_config: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "rule_key",
            "version",
            name="uq_policy_rules_rule_key_version",
        ),
        CheckConstraint(
            "version > 0",
            name="valid_version",
        ),
        CheckConstraint(
            "effect IN ('allow', 'require_approval', 'deny')",
            name="valid_effect",
        ),
    )
