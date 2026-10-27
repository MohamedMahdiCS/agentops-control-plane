"""Security tests for server-verified operator authentication."""

import hashlib
from types import SimpleNamespace
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.app.core import operator_auth

TEST_TOKEN = "test-only-operator-token-" + "a" * 40
TEST_HASH = hashlib.sha256(TEST_TOKEN.encode()).hexdigest()


@pytest.fixture
def client():
    app = FastAPI()

    @app.get("/protected")
    def protected(
        principal: Annotated[
            operator_auth.OperatorPrincipal,
            Depends(operator_auth.require_operator),
        ],
    ):
        return {
            "operator_id": principal.operator_id,
            "role": principal.role,
        }

    return TestClient(app)


def configure_operator(
    monkeypatch, token_hash=TEST_HASH, operator_id="verified-operator"
):
    monkeypatch.setattr(
        operator_auth,
        "Settings",
        lambda: SimpleNamespace(
            operator_token_sha256=(
                SecretStr(token_hash) if token_hash is not None else None
            ),
            operator_id=operator_id,
        ),
    )


def test_authentication_fails_closed_when_unconfigured(client, monkeypatch):
    configure_operator(monkeypatch, token_hash=None)

    response = client.get(
        "/protected",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    )

    assert response.status_code == 503


def test_missing_credentials_are_rejected(client, monkeypatch):
    configure_operator(monkeypatch)

    response = client.get("/protected")

    assert response.status_code == 401


def test_invalid_token_is_rejected(client, monkeypatch):
    configure_operator(monkeypatch)

    response = client.get(
        "/protected",
        headers={"Authorization": "Bearer " + "wrong-token-" + "x" * 40},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_valid_token_authenticates_server_identity(client, monkeypatch):
    configure_operator(monkeypatch)

    response = client.get(
        "/protected",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "operator_id": "verified-operator",
        "role": "operator",
    }


def test_caller_cannot_spoof_operator_identity(client, monkeypatch):
    configure_operator(monkeypatch)

    response = client.get(
        "/protected",
        headers={
            "Authorization": f"Bearer {TEST_TOKEN}",
            "X-Operator-ID": "attacker",
            "X-Operator-Role": "admin",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "operator_id": "verified-operator",
        "role": "operator",
    }


@pytest.mark.parametrize(
    "invalid_hash",
    ["", "not-a-sha256-hash", "g" * 64],
)
def test_invalid_server_configuration_fails_closed(client, monkeypatch, invalid_hash):
    configure_operator(monkeypatch, token_hash=invalid_hash)

    response = client.get(
        "/protected",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    )

    assert response.status_code == 503


def test_invalid_operator_identity_fails_closed(client, monkeypatch):
    configure_operator(
        monkeypatch,
        operator_id="attacker\nadmin",
    )

    response = client.get(
        "/protected",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    )

    assert response.status_code == 503
