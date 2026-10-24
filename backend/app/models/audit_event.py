from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="RESTRICT"),
        nullable=True,
    )

    actor_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    actor_identifier: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    event_type: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    resource_type: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    resource_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    event_payload: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "ix_audit_events_run_id_created_at",
            "run_id",
            "created_at",
        ),
    )
