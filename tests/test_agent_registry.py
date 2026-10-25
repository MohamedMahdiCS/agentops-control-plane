import os
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app


def test_agent_registration_rejects_invalid_requests() -> None:
    invalid_payloads = [
        {"name": "", "agent_type": "incident_response"},
        {"name": "A" * 81, "agent_type": "incident_response"},
        {"name": "Test", "agent_type": "unsupported"},
        {
            "name": "Test",
            "description": "A" * 501,
            "agent_type": "incident_response",
        },
    ]

    with TestClient(create_app()) as client:
        for payload in invalid_payloads:
            response = client.post("/api/v1/agents", json=payload)
            assert response.status_code == 422, response.text


def test_agent_listing_rejects_invalid_parameters() -> None:
    with TestClient(create_app()) as client:
        for limit in (0, 101):
            response = client.get(
                "/api/v1/agents",
                params={"limit": limit},
            )
            assert response.status_code == 422

        response = client.get(
            "/api/v1/agents",
            params={"cursor": "!"},
        )
        assert response.status_code == 400


def test_agent_listing_returns_valid_response() -> None:
    if os.getenv("AGENTOPS_RUN_DB_INTEGRATION") != "1":
        pytest.skip("Database integration tests require explicit activation")

    with TestClient(create_app()) as client:
        response = client.get("/api/v1/agents", params={"limit": 20})

        assert response.status_code == 200, response.text

        data = response.json()
        assert isinstance(data["agents"], list)
        assert len(data["agents"]) <= 20
        assert data["next_cursor"] is None or isinstance(data["next_cursor"], str)

        for agent in data["agents"]:
            UUID(agent["id"])
            assert agent["agent_type"] == "incident_response"
