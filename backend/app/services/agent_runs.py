import hashlib
import json
from copy import deepcopy
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.agent import Agent
from backend.app.models.agent_run import AgentRun
from backend.app.schemas.agent_run import AgentRunCreate

SUPPORTED_INCIDENTS = frozenset({"INC-1042"})


class AgentNotFoundError(Exception):
    pass


class AgentDisabledError(Exception):
    pass


class UnsupportedIncidentError(Exception):
    pass


class IdempotencyConflictError(Exception):
    pass


def request_fingerprint(incident_id: str) -> str:
    request = {
        "execution_mode": "deterministic",
        "incident_id": incident_id,
        "version": 1,
    }
    canonical = json.dumps(request, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def create_agent_run(
    session: AsyncSession,
    agent_id: UUID,
    payload: AgentRunCreate,
    idempotency_key: str | None = None,
) -> AgentRun:
    fingerprint = (
        request_fingerprint(payload.incident_id)
        if idempotency_key is not None
        else None
    )

    async with session.begin():
        # Resolve previously accepted requests before current-state checks.
        if idempotency_key is not None:
            existing_run = await session.scalar(
                select(AgentRun).where(
                    AgentRun.agent_id == agent_id,
                    AgentRun.idempotency_key == idempotency_key,
                )
            )

            if existing_run is not None:
                if existing_run.request_fingerprint != fingerprint:
                    raise IdempotencyConflictError()
                return existing_run

        if payload.incident_id not in SUPPORTED_INCIDENTS:
            raise UnsupportedIncidentError(payload.incident_id)

        agent = await session.scalar(
            select(Agent).where(Agent.id == agent_id).with_for_update(read=True)
        )

        if agent is None:
            raise AgentNotFoundError()

        if agent.status != "active":
            raise AgentDisabledError()

        statement = (
            insert(AgentRun)
            .values(
                id=uuid4(),
                agent_id=agent.id,
                incident_id=payload.incident_id,
                status="queued",
                agent_config_version=agent.config_version,
                agent_config_snapshot=deepcopy(agent.config_json),
                execution_mode="deterministic",
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
            )
            .on_conflict_do_nothing(constraint="uq_agent_runs_agent_id_idempotency_key")
            .returning(AgentRun)
        )

        result = await session.scalar(statement)

        if result is None:
            result = await session.scalar(
                select(AgentRun).where(
                    AgentRun.agent_id == agent_id,
                    AgentRun.idempotency_key == idempotency_key,
                )
            )

            if result is None:
                raise RuntimeError("Conflicting run could not be retrieved")

            if result.request_fingerprint != fingerprint:
                raise IdempotencyConflictError()

    return result


async def get_agent_run(
    session: AsyncSession,
    run_id: UUID,
) -> AgentRun | None:
    return await session.get(AgentRun, run_id)
