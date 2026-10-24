from fastapi.testclient import TestClient

from backend.app.main import create_app


def test_health_endpoint_returns_expected_response() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "agentops-api",
        "version": "0.1.0",
    }


def test_openapi_documents_health_endpoint() -> None:
    client = TestClient(create_app())

    response = client.get("/openapi.json")

    assert response.status_code == 200

    schema = response.json()

    assert schema["info"]["title"] == "AgentOps Control Plane API"
    assert schema["info"]["version"] == "0.1.0"

    health_endpoint = schema["paths"]["/api/v1/health"]["get"]

    assert "200" in health_endpoint["responses"]
    assert "application/json" in health_endpoint["responses"]["200"]["content"]
