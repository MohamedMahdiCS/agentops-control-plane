"""Overview endpoint: authentication, contract and real aggregation."""

import asyncio
import hashlib
import os
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, delete, insert
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from backend.app.api.v1 import overview
from backend.app.benchmark.manifest import ManifestStore
from backend.app.core import operator_auth
from backend.app.core.config import Settings
from backend.app.core.dependencies import get_db_session
from backend.app.core.session import create_session_factory
from backend.app.models.agent import Agent
from backend.app.models.agent_run import AgentRun
from backend.app.models.audit_event import AuditEvent
from backend.app.models.policy_decision import PolicyDecision
from backend.app.models.trace_span import TraceSpan
from backend.app.runtime.runner import run_worker_once
from backend.app.services import overview as service
from tests.test_benchmark_analysis import manifest, outcome

TOKEN = "test-only-overview-token-" + "a" * 40
TOKEN_HASH = hashlib.sha256(TOKEN.encode()).hexdigest()
NOW = datetime.now(UTC)


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr(
        operator_auth,
        "Settings",
        lambda: SimpleNamespace(
            operator_token_sha256=SecretStr(TOKEN_HASH), operator_id="overview-operator"
        ),
    )
    store = ManifestStore(tmp_path)
    calls = []

    async def fake_build(session, store_arg):
        calls.append(store_arg)
        return service.Overview(
            generated_at=NOW,
            runs_total=3,
            runs_by_status={"completed": 2, "failed": 1},
            runs_last_24h=3,
            runs_hourly=[0] * 23 + [3],
            evaluations_total=4,
            evaluations_passed=3,
            evaluations_failed=0,
            evaluations_inconclusive=1,
            pending_approvals=1,
            latest_benchmark=store_arg.write(manifest(outcome("B01"))),
            recent_events=[
                service.RecentEvent(
                    uuid4(), "tool.authorization", "worker", uuid4(), NOW
                )
            ],
        )

    monkeypatch.setattr(overview, "build_overview", fake_build)
    monkeypatch.setattr(overview, "configured_store", lambda: store)
    app = FastAPI()
    app.include_router(overview.router, prefix="/api/v1")

    async def fake_db():
        yield object()

    app.dependency_overrides[get_db_session] = fake_db
    with TestClient(app) as client:
        yield client, calls


def test_overview_requires_operator(api):
    client, calls = api

    assert client.get("/api/v1/overview").status_code == 401
    assert (
        client.get(
            "/api/v1/overview", headers={"Authorization": "Bearer bad-" + "x" * 40}
        ).status_code
        == 401
    )
    assert calls == []


def test_overview_contract_and_pass_rate(api):
    client, _ = api

    response = client.get(
        "/api/v1/overview", headers={"Authorization": f"Bearer {TOKEN}"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["runs"]["last_24h"] == 3
    assert len(body["runs"]["hourly"]) == 24
    # Inconclusive results count against the pass rate.
    assert body["evaluations"]["pass_rate"] == 0.75
    assert body["latest_benchmark"]["gate"] == "passed"
    assert set(body["recent_events"][0]) == {
        "id",
        "event_type",
        "actor_type",
        "run_id",
        "created_at",
    }


def test_overview_aggregates_real_records(tmp_path):
    if os.getenv("AGENTOPS_RUN_DB_INTEGRATION") != "1":
        pytest.skip("Database integration tests require activation")
    url = make_url(Settings().database_url.get_secret_value())
    if url.database != "agentops_test":
        pytest.fail("Refusing overview tests outside agentops_test")

    agent_id, run_id = uuid4(), uuid4()
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            insert(Agent).values(
                id=agent_id,
                name="Overview Test",
                agent_type="incident_response",
                status="active",
                config_version=1,
                config_json={},
            )
        )
        connection.execute(
            insert(AgentRun).values(
                id=run_id,
                agent_id=agent_id,
                incident_id="INC-1042",
                status="queued",
                agent_config_version=1,
                agent_config_snapshot={},
                execution_mode="deterministic",
            )
        )

    async def run():
        async_engine = create_async_engine(url.render_as_string(hide_password=False))
        try:
            factory = create_session_factory(async_engine)
            await run_worker_once(factory, "overview-test-worker", run_id=run_id)
            async with factory() as session:
                return await service.build_overview(session, ManifestStore(tmp_path))
        finally:
            await async_engine.dispose()

    try:
        data = asyncio.run(run())
    finally:
        with engine.begin() as connection:
            for model in (AuditEvent, PolicyDecision, TraceSpan):
                connection.execute(delete(model).where(model.run_id == run_id))
            connection.execute(delete(AgentRun).where(AgentRun.id == run_id))
            connection.execute(delete(Agent).where(Agent.id == agent_id))
        engine.dispose()

    assert data.runs_by_status["completed"] >= 1
    assert data.runs_last_24h >= 1
    assert sum(data.runs_hourly) == data.runs_last_24h
    assert data.runs_total == sum(data.runs_by_status.values())
    assert any(event.run_id == run_id for event in data.recent_events)
    assert data.latest_benchmark is None
