"""HTTP security tests for the authenticated approval API."""

import hashlib
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.app.api.v1 import approvals
from backend.app.core import operator_auth
from backend.app.core.dependencies import get_db_session
from backend.app.services.approval_decisions import (
    ApprovalConflictError,
    ApprovalDecisionResult,
    ApprovalNotFoundError,
)

TOKEN = "test-only-approval-token-" + "a" * 40
TOKEN_HASH = hashlib.sha256(TOKEN.encode()).hexdigest()
APPROVAL_ID = uuid4()
URL = f"/api/v1/approvals/{APPROVAL_ID}/decision"

VALID_PAYLOAD = {
    "decision": "approved",
    "reason": "Evidence reviewed and operational risks assessed.",
}


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(
        operator_auth,
        "Settings",
        lambda: SimpleNamespace(
            operator_token_sha256=SecretStr(TOKEN_HASH),
            operator_id="trusted-operator",
        ),
    )

    app = FastAPI()
    app.include_router(approvals.router, prefix="/api/v1")

    async def fake_db_session():
        yield object()

    app.dependency_overrides[get_db_session] = fake_db_session

    calls = []

    async def fake_decision(
        session,
        approval_id,
        *,
        decision,
        operator_id,
        reason,
        idempotency_key,
    ):
        calls.append(
            {
                "approval_id": approval_id,
                "decision": decision,
                "operator_id": operator_id,
                "reason": reason,
                "idempotency_key": idempotency_key,
            }
        )

        return ApprovalDecisionResult(
            approval_id=approval_id,
            status=decision,
            run_status=("awaiting_approval" if decision == "approved" else "failed"),
            idempotent=False,
        )

    monkeypatch.setattr(
        approvals,
        "decide_pending_approval",
        fake_decision,
    )

    with TestClient(app) as client:
        yield client, calls


def headers(token=TOKEN):
    return {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": "approval-request-001",
    }


def test_missing_authentication_rejected(api):
    client, calls = api
    response = client.post(
        URL,
        json=VALID_PAYLOAD,
        headers={"Idempotency-Key": "approval-request-001"},
    )
    assert response.status_code == 401
    assert calls == []


def test_invalid_token_rejected(api):
    client, calls = api
    response = client.post(
        URL,
        json=VALID_PAYLOAD,
        headers=headers("wrong-token-" + "x" * 40),
    )
    assert response.status_code == 401
    assert calls == []


def test_valid_operator_can_record_approval(api):
    client, calls = api
    response = client.post(
        URL,
        json=VALID_PAYLOAD,
        headers=headers(),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert response.json()["run_status"] == "awaiting_approval"
    assert len(calls) == 1
    assert calls[0]["operator_id"] == "trusted-operator"
    assert calls[0]["idempotency_key"] == "approval-request-001"


def test_caller_cannot_spoof_operator_identity(api):
    client, calls = api

    request_headers = headers()
    request_headers["X-Operator-ID"] = "attacker"
    request_headers["X-Operator-Role"] = "admin"

    response = client.post(
        URL,
        json=VALID_PAYLOAD,
        headers=request_headers,
    )

    assert response.status_code == 200
    assert calls[0]["operator_id"] == "trusted-operator"


def test_authentication_unconfigured_fails_closed(api, monkeypatch):
    client, calls = api

    monkeypatch.setattr(
        operator_auth,
        "Settings",
        lambda: SimpleNamespace(
            operator_token_sha256=None,
            operator_id=None,
        ),
    )

    response = client.post(
        URL,
        json=VALID_PAYLOAD,
        headers=headers(),
    )

    assert response.status_code == 503
    assert calls == []


def test_operator_identity_in_body_is_rejected(api):
    client, calls = api

    response = client.post(
        URL,
        json={
            **VALID_PAYLOAD,
            "operator_id": "attacker",
        },
        headers=headers(),
    )

    assert response.status_code == 422
    assert calls == []


def test_missing_idempotency_key_rejected(api):
    client, calls = api

    response = client.post(
        URL,
        json=VALID_PAYLOAD,
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 422
    assert calls == []


def test_short_reason_rejected(api):
    client, calls = api

    response = client.post(
        URL,
        json={
            "decision": "approved",
            "reason": "yes",
        },
        headers=headers(),
    )

    assert response.status_code == 422
    assert calls == []


def test_authenticated_rejection_is_recorded(api):
    client, calls = api

    response = client.post(
        URL,
        json={
            "decision": "rejected",
            "reason": "Insufficient evidence to permit this operation.",
        },
        headers=headers(),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["run_status"] == "failed"
    assert calls[0]["decision"] == "rejected"


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (ApprovalNotFoundError("missing"), 404),
        (ApprovalConflictError("conflict"), 409),
        (ValueError("invalid"), 422),
    ],
)
def test_approval_service_errors_are_safely_mapped(
    api, monkeypatch, error, expected_status
):
    client, _ = api

    async def failing_decision(*args, **kwargs):
        raise error

    monkeypatch.setattr(
        approvals,
        "decide_pending_approval",
        failing_decision,
    )

    response = client.post(
        URL,
        json=VALID_PAYLOAD,
        headers=headers(),
    )

    assert response.status_code == expected_status
    assert str(error) not in response.text
