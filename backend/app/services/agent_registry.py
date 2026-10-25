from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.agent import Agent
from backend.app.schemas.agent import AgentCreate


async def register_agent(
    session: AsyncSession,
    payload: AgentCreate,
) -> Agent:
    agent = Agent(
        name=payload.name,
        description=payload.description,
        agent_type=payload.agent_type,
    )

    session.add(agent)
    await session.commit()
    await session.refresh(agent)

    return agent


def _encode_cursor(agent: Agent) -> str:
    value = f"{agent.created_at.isoformat()}|{agent.id}"
    return urlsafe_b64encode(value.encode()).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        if not cursor or len(cursor) > 256:
            raise ValueError("Invalid cursor length")

        raw = urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))

        if urlsafe_b64encode(raw).decode("ascii").rstrip("=") != cursor:
            raise ValueError("Invalid cursor encoding")

        timestamp, agent_id = raw.decode("utf-8").split("|", 1)
        created_at = datetime.fromisoformat(timestamp)

        if created_at.tzinfo is None:
            raise ValueError("Cursor timestamp must have a timezone")

        return created_at, UUID(agent_id)

    except (ValueError, UnicodeDecodeError, Base64Error) as exc:
        raise ValueError("Invalid agent pagination cursor") from exc


async def list_agents(
    session: AsyncSession,
    limit: int = 20,
    cursor: str | None = None,
) -> tuple[list[Agent], str | None]:
    if not 1 <= limit <= 100:
        raise ValueError("Page limit must be between 1 and 100")

    statement = (
        select(Agent).order_by(Agent.created_at.asc(), Agent.id.asc()).limit(limit + 1)
    )

    if cursor is not None:
        created_at, agent_id = _decode_cursor(cursor)
        statement = statement.where(
            tuple_(Agent.created_at, Agent.id) > (created_at, agent_id)
        )

    result = await session.scalars(statement)
    rows = list(result.all())

    agents = rows[:limit]
    next_cursor = _encode_cursor(agents[-1]) if len(rows) > limit else None

    return agents, next_cursor
