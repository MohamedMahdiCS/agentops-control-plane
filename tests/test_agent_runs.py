import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from backend.app.core.config import Settings
from backend.app.main import create_app


def isolated_test_database_url():
    url = make_url(Settings().database_url.get_secret_value())
    assert url.database == "agentops_test", (
        "Refusing integration test outside agentops_test"
    )
    return url


@pytest.fixture
def client():
    if os.getenv("AGENTOPS_RUN_DB_INTEGRATION") != "1":
        pytest.skip("Database integration tests require activation")

    isolated_test_database_url()

    with TestClient(create_app()) as test_client:
        yield test_client


def register_test_agent(client):
    response = client.post(
        "/api/v1/agents",
        json={
            "name": f"Day 6 Test {uuid4().hex[:12]}",
            "agent_type": "incident_response",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def submit_run(client, agent_id, key, incident_id="INC-1042"):
    return client.post(
        f"/api/v1/agents/{agent_id}/runs",
        json={"incident_id": incident_id},
        headers={"Idempotency-Key": key},
    )


def test_run_creation_retrieval_and_snapshot(client):
    agent_id = register_test_agent(client)
    key = f"test-{uuid4().hex}"

    created = submit_run(client, agent_id, key)
    assert created.status_code == 202, created.text

    run_id = created.json()["run_id"]
    assert created.json()["status"] == "queued"
    assert created.headers["location"] == f"/api/v1/runs/{run_id}"

    retry = submit_run(client, agent_id, key)
    assert retry.status_code == 202
    assert retry.json()["run_id"] == run_id

    retrieved = client.get(f"/api/v1/runs/{run_id}")
    assert retrieved.status_code == 200
    assert retrieved.json()["status"] == "queued"
    assert retrieved.json()["agent_config_version"] == 1

    engine = create_engine(isolated_test_database_url())
    try:
        with engine.begin() as connection:
            original_snapshot = connection.execute(
                text("SELECT agent_config_snapshot FROM agent_runs WHERE id = :run_id"),
                {"run_id": run_id},
            ).scalar_one()

            connection.execute(
                text(
                    "UPDATE agents "
                    "SET config_version = 2, "
                    "config_json = CAST(:config AS jsonb) "
                    "WHERE id = :agent_id"
                ),
                {
                    "agent_id": agent_id,
                    "config": '{"updated": true}',
                },
            )

            preserved_snapshot = connection.execute(
                text("SELECT agent_config_snapshot FROM agent_runs WHERE id = :run_id"),
                {"run_id": run_id},
            ).scalar_one()

        assert preserved_snapshot == original_snapshot
    finally:
        engine.dispose()


def test_concurrent_idempotent_submissions(client):
    agent_id = register_test_agent(client)
    key = f"concurrent-{uuid4().hex}"

    with ThreadPoolExecutor(max_workers=6) as executor:
        responses = list(
            executor.map(
                lambda _: submit_run(client, agent_id, key),
                range(6),
            )
        )

    assert all(response.status_code == 202 for response in responses), [
        (response.status_code, response.text) for response in responses
    ]

    run_ids = {response.json()["run_id"] for response in responses}
    assert len(run_ids) == 1

    engine = create_engine(isolated_test_database_url())
    try:
        with engine.connect() as connection:
            count = connection.execute(
                text(
                    "SELECT COUNT(*) FROM agent_runs "
                    "WHERE agent_id = :agent_id "
                    "AND idempotency_key = :key"
                ),
                {"agent_id": agent_id, "key": key},
            ).scalar_one()

        assert count == 1
    finally:
        engine.dispose()


def test_conflicting_idempotency_key_returns_409(client):
    agent_id = register_test_agent(client)
    key = f"conflict-{uuid4().hex}"

    first = submit_run(client, agent_id, key)
    assert first.status_code == 202

    conflicting = submit_run(
        client,
        agent_id,
        key,
        incident_id="INC-9999",
    )

    assert conflicting.status_code == 409, conflicting.text


def test_retry_after_agent_disabled_returns_original_run(client):
    agent_id = register_test_agent(client)
    key = f"disabled-{uuid4().hex}"

    first = submit_run(client, agent_id, key)
    assert first.status_code == 202
    original_run_id = first.json()["run_id"]

    engine = create_engine(isolated_test_database_url())
    try:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE agents SET status = 'disabled' WHERE id = :agent_id"),
                {"agent_id": agent_id},
            )
    finally:
        engine.dispose()

    retry = submit_run(client, agent_id, key)
    assert retry.status_code == 202, retry.text
    assert retry.json()["run_id"] == original_run_id
