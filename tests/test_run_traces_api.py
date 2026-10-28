"""Security and response-contract tests for the run trace API."""

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.app.api.v1 import runs
from backend.app.core import operator_auth
from backend.app.core.dependencies import get_db_session

TOKEN = "test-only-trace-token-" + "a" * 40
TOKEN_HASH = hashlib.sha256(TOKEN.encode()).hexdigest()
RUN_ID = uuid4()


@pytest.fixture
def trace_api(monkeypatch):
    monkeypatch.setattr(
        operator_auth,
        "Settings",
        lambda: SimpleNamespace(
            operator_token_sha256=SecretStr(TOKEN_HASH),
            operator_id="test-trace-operator",
        ),
    )

    now = datetime.now(UTC)

    span = SimpleNamespace(
        id=uuid4(),
        parent_span_id=None,
        span_type="tool_call",
        name="get_incident",
        status="ok",
        started_at=now,
        ended_at=now,
        duration_ms=12,
        safe_summary="SUCCESS",
        sanitized_attributes={"secret": "DO_NOT_EXPOSE"},
    )

    event = SimpleNamespace(
        id=uuid4(),
        event_type="tool.authorization",
        actor_type="worker",
        actor_identifier="DO_NOT_EXPOSE",
        created_at=now,
        event_payload={"secret": "DO_NOT_EXPOSE"},
    )

    state = {
        "spans": [span],
        "events": [event],
        "queries": 0,
        "lookups": 0,
    }

    class FakeSession:
        async def scalars(self, statement):
            state["queries"] += 1
            sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
            assert "LIMIT 101" in sql

            if "FROM trace_spans" in sql:
                return SimpleNamespace(all=lambda: state["spans"])

            if "FROM audit_events" in sql:
                return SimpleNamespace(all=lambda: state["events"])

            raise AssertionError("Unexpected database query")

    async def fake_db_session():
        yield FakeSession()

    async def fake_get_agent_run(session, run_id):
        state["lookups"] += 1
        if run_id == RUN_ID:
            return SimpleNamespace(id=RUN_ID)
        return None

    monkeypatch.setattr(runs, "get_agent_run", fake_get_agent_run)

    app = FastAPI()
    app.include_router(runs.router, prefix="/api/v1")
    app.dependency_overrides[get_db_session] = fake_db_session

    with TestClient(app) as client:
        yield client, state


def authorization_headers(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


def test_trace_endpoint_requires_authentication(trace_api):
    client, state = trace_api

    response = client.get(f"/api/v1/runs/{RUN_ID}/traces")

    assert response.status_code == 401
    assert state["lookups"] == 0
    assert state["queries"] == 0


def test_trace_endpoint_rejects_invalid_token(trace_api):
    client, state = trace_api

    response = client.get(
        f"/api/v1/runs/{RUN_ID}/traces",
        headers=authorization_headers("invalid-" + "x" * 40),
    )

    assert response.status_code == 401
    assert state["lookups"] == 0
    assert state["queries"] == 0


def test_trace_response_excludes_sensitive_fields(trace_api):
    client, state = trace_api

    response = client.get(
        f"/api/v1/runs/{RUN_ID}/traces",
        headers=authorization_headers(),
    )

    assert response.status_code == 200, response.text

    payload = response.json()

    assert payload["run_id"] == str(RUN_ID)
    assert len(payload["spans"]) == 1
    assert len(payload["audit_events"]) == 1
    assert payload["spans"][0]["duration_ms"] == 12
    assert payload["spans"][0]["safe_summary"] == "SUCCESS"

    assert "sanitized_attributes" not in payload["spans"][0]
    assert "event_payload" not in payload["audit_events"][0]
    assert "actor_identifier" not in payload["audit_events"][0]
    assert "DO_NOT_EXPOSE" not in response.text

    assert state["queries"] == 2


def test_trace_collections_are_bounded_and_report_truncation(trace_api):
    client, state = trace_api

    state["spans"] = state["spans"] * 101
    state["events"] = state["events"] * 101

    response = client.get(
        f"/api/v1/runs/{RUN_ID}/traces",
        headers=authorization_headers(),
    )

    assert response.status_code == 200, response.text

    payload = response.json()

    assert len(payload["spans"]) == 100
    assert len(payload["audit_events"]) == 100
    assert payload["spans_truncated"] is True
    assert payload["audit_events_truncated"] is True


def test_unknown_run_returns_404_without_querying_traces(trace_api):
    client, state = trace_api

    response = client.get(
        f"/api/v1/runs/{uuid4()}/traces",
        headers=authorization_headers(),
    )

    assert response.status_code == 404
    assert state["queries"] == 0
