"""Environment validation and HTTP hardening."""

import hashlib

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.app.core.config import (
    ConfigurationError,
    Settings,
    validate_runtime_settings,
)
from backend.app.main import create_app

DIGEST = hashlib.sha256(b"test-only-production-token-" + b"x" * 40).hexdigest()


def settings(**values) -> Settings:
    defaults = {"database_url": SecretStr("postgresql://localhost/unused")}
    return Settings.model_construct(**(defaults | values))


def test_production_requires_operator_authentication():
    with pytest.raises(ConfigurationError):
        validate_runtime_settings(settings(app_env="production"))
    with pytest.raises(ConfigurationError):
        validate_runtime_settings(
            settings(
                app_env="production",
                operator_token_sha256=SecretStr("not-a-digest"),
                operator_id="ops",
            )
        )

    validate_runtime_settings(
        settings(
            app_env="production",
            operator_token_sha256=SecretStr(DIGEST),
            operator_id="ops",
        )
    )


@pytest.mark.parametrize(
    ("origins", "environment"),
    [
        ("*", "development"),
        ("https://ok.example, not a url", "development"),
        ("http://console.example.com", "production"),
    ],
)
def test_unsafe_cors_origins_are_rejected(origins, environment):
    with pytest.raises(ConfigurationError):
        validate_runtime_settings(
            settings(
                app_env=environment,
                cors_origins=origins,
                operator_token_sha256=SecretStr(DIGEST),
                operator_id="ops",
            )
        )


def test_security_headers_and_no_store_on_api():
    client = TestClient(create_app(settings(app_env="development")))

    response = client.get("/api/v1/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cache-Control"] == "no-store"


def test_production_hides_interactive_docs():
    app = create_app(
        settings(
            app_env="production",
            operator_token_sha256=SecretStr(DIGEST),
            operator_id="ops",
        )
    )
    client = TestClient(app)

    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/api/v1/health").status_code == 200


def test_cors_allowlist_is_exact():
    client = TestClient(
        create_app(settings(cors_origins="https://console.example.com"))
    )

    allowed = client.options(
        "/api/v1/health",
        headers={
            "Origin": "https://console.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    denied = client.get(
        "/api/v1/health", headers={"Origin": "https://evil.example.com"}
    )

    assert (
        allowed.headers["access-control-allow-origin"] == "https://console.example.com"
    )
    assert "access-control-allow-origin" not in denied.headers
