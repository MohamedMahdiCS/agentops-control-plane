from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Integer,
    String,
    column,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))

    agent_type: Mapped[str] = mapped_column(
        String(40), nullable=False, default="incident_response"
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    config_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(column("agent_type") == "incident_response"),
        CheckConstraint(column("status").in_(("active", "disabled"))),
        CheckConstraint(column("config_version") > 0),
    )
