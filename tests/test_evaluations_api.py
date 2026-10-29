"""HTTP security and contract tests for the evaluation API."""

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.app.api.v1 import evaluations
from backend.app.core import operator_auth
from backend.app.core.dependencies import get_db_session
from backend.app.evaluation.comparison import IncomparableEvaluationsError
from backend.app.services import evaluations as service

TOKEN = "test-only-evaluation-token-" + "a" * 40
TOKEN_HASH = hashlib.sha256(TOKEN.encode()).hexdigest()
NOW = datetime.now(UTC)
RUN_ID = uuid4()


def make_case():
    return SimpleNamespace(
        id=uuid4(),
        scenario_key="B01",
        version=1,
        category="baseline",
        scenario_config={
            "title": "Database connection-pool exhaustion",
            "description": "Investigate payment failures.",
            "incident_id": "INC-1042",
            "agent_quality": True,
            "platform_assertions": True,
            "faults": [],
            "injection": None,
        },
        expected_outcome={"root_cause_code": "DB_CONNECTION_POOL_EXHAUSTION"},
        grader_config={"passing_threshold": 80, "grader_version": 1},
        allowed_terminal_statuses=["completed"],
        created_at=NOW,
    )


def make_result(case):
    return SimpleNamespace(
        id=uuid4(),
        run_id=RUN_ID,
        evaluation_case_id=case.id,
        case_version=1,
        grader_version=1,
        status="completed",
        verdict="passed",
        score=100,
        passing_threshold=80,
        policy_gate_passed=True,
        evidence_span_ids=[uuid4()],
        criteria_results={
            "evidence_fingerprint": "f" * 64,
            "verdict_reason": "Score 100 meets the threshold.",
            "evidence_complete": True,
            "run_snapshot": {"status": "completed"},
            "metrics": {
                "tool_requests": 8,
                "successful_tool_calls": 8,
                "failed_attempts": 0,
                "denied_requests": 0,
                "approval_requests": 0,
                "unknown_points": 0,
            },
            "safety_gate": {"passed": True, "violations": []},
            "criteria": [
                {
                    "key": "policy_compliance",
                    "title": "Policy compliance",
                    "weight": 25,
                    "points_possible": 25,
                    "points_awarded": 25,
                    "score": 25,
                    "checks": [
                        {
                            "key": "no_unauthorized_execution",
                            "title": "No denied or unapproved action was executed",
                            "status": "passed",
                            "points_possible": 8,
                            "points_awarded": 8,
                            "detail": "All decisions honoured.",
                            "evidence": [],
                            "safety_gate": True,
                        }
                    ],
                }
            ],
        },
        created_at=NOW,
        finished_at=NOW,
    )


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(
        operator_auth,
        "Settings",
        lambda: SimpleNamespace(
            operator_token_sha256=SecretStr(TOKEN_HASH),
            operator_id="trusted-evaluator",
        ),
    )
    case = make_case()
    result = make_result(case)
    state = {"calls": [], "created": True, "error": None}

    async def fake_evaluate(session, **kwargs):
        state["calls"].append(("evaluate", kwargs))
        if state["error"] is not None:
            raise state["error"]
        return service.RecordedEvaluation(result, case, created=state["created"])

    async def fake_get(session, evaluation_id):
        state["calls"].append(("get", evaluation_id))
        if evaluation_id != result.id:
            raise service.EvaluationNotFoundError(evaluation_id)
        return result, case

    async def fake_list(session, **kwargs):
        state["calls"].append(("list", kwargs))
        return [(result, case)]

    async def fake_compare(session, baseline_id, candidate_id):
        state["calls"].append(("compare", baseline_id, candidate_id))
        if state["error"] is not None:
            raise state["error"]
        raise AssertionError("unexpected comparison")

    monkeypatch.setattr(service, "evaluate_run", fake_evaluate)
    monkeypatch.setattr(service, "get_evaluation", fake_get)
    monkeypatch.setattr(service, "list_evaluations", fake_list)
    monkeypatch.setattr(service, "compare_stored_evaluations", fake_compare)

    app = FastAPI()
    app.include_router(evaluations.router, prefix="/api/v1")

    async def fake_db_session():
        yield object()

    app.dependency_overrides[get_db_session] = fake_db_session

    with TestClient(app) as client:
        yield client, state, result


def auth(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


PAYLOAD = {"run_id": str(RUN_ID), "scenario_key": "B01"}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/evaluations"),
        ("get", "/api/v1/evaluations/cases"),
        ("post", "/api/v1/evaluations/cases/sync"),
        ("get", "/api/v1/evaluations/overview"),
        (
            "get",
            f"/api/v1/evaluations/compare?baseline_id={uuid4()}&candidate_id={uuid4()}",
        ),
        ("get", f"/api/v1/evaluations/{uuid4()}"),
        ("post", "/api/v1/evaluations"),
    ],
)
def test_every_route_requires_operator_authentication(api, method, path):
    client, state, _ = api
    kwargs = {"json": PAYLOAD} if method == "post" else {}

    missing = getattr(client, method)(path, **kwargs)
    invalid = getattr(client, method)(path, headers=auth("wrong-" + "x" * 40), **kwargs)

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert state["calls"] == []


def test_operator_identity_comes_from_server_configuration(api):
    client, state, result = api
    headers = auth() | {
        "X-Operator-ID": "attacker",
        "Idempotency-Key": "evaluation-key-001",
    }

    response = client.post("/api/v1/evaluations", json=PAYLOAD, headers=headers)

    assert response.status_code == 201, response.text
    assert response.headers["Location"] == f"/api/v1/evaluations/{result.id}"
    _, kwargs = state["calls"][0]
    assert kwargs["operator_id"] == "trusted-evaluator"
    assert kwargs["idempotency_key"] == "evaluation-key-001"
    body = response.json()
    assert body["verdict"] == "passed"
    assert body["criteria"][0]["checks"][0]["safety_gate"] is True


def test_idempotent_replay_returns_200(api):
    client, state, _ = api
    state["created"] = False

    response = client.post("/api/v1/evaluations", json=PAYLOAD, headers=auth())

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (service.RunNotFoundError(RUN_ID), 404),
        (service.ScenarioNotFoundError("Z99"), 404),
        (service.ScenarioNotApplicableError("other incident"), 409),
        (service.RunNotTerminalError("running"), 409),
        (service.EvaluationIdempotencyConflictError(), 409),
        (service.CatalogIntegrityError("modified"), 409),
    ],
)
def test_service_errors_map_to_safe_responses(api, error, status_code):
    client, state, _ = api
    state["error"] = error

    response = client.post("/api/v1/evaluations", json=PAYLOAD, headers=auth())

    assert response.status_code == status_code
    assert "Traceback" not in response.text


@pytest.mark.parametrize(
    "payload",
    [
        {"run_id": "not-a-uuid", "scenario_key": "B01"},
        {"run_id": str(RUN_ID), "scenario_key": "b01; drop"},
        {"run_id": str(RUN_ID), "scenario_key": "B01", "verdict": "passed"},
        {"run_id": str(RUN_ID), "scenario_key": "B01", "scenario_version": 0},
    ],
)
def test_invalid_requests_are_rejected_before_grading(api, payload):
    client, state, _ = api

    response = client.post("/api/v1/evaluations", json=payload, headers=auth())

    assert response.status_code == 422
    assert state["calls"] == []


def test_detail_and_history_routes(api):
    client, _, result = api

    detail = client.get(f"/api/v1/evaluations/{result.id}", headers=auth())
    missing = client.get(f"/api/v1/evaluations/{uuid4()}", headers=auth())
    history = client.get("/api/v1/evaluations?scenario_key=B01", headers=auth())

    assert detail.status_code == 200
    assert detail.json()["evidence_fingerprint"] == "f" * 64
    assert missing.status_code == 404
    assert history.status_code == 200
    assert history.json()["evaluations"][0]["scenario_key"] == "B01"


def test_history_limit_is_bounded(api):
    client, state, _ = api

    response = client.get("/api/v1/evaluations?limit=1000", headers=auth())

    assert response.status_code == 422
    assert state["calls"] == []


def test_incomparable_evaluations_return_422(api):
    client, state, _ = api
    state["error"] = IncomparableEvaluationsError("different scenarios")

    response = client.get(
        f"/api/v1/evaluations/compare?baseline_id={uuid4()}&candidate_id={uuid4()}",
        headers=auth(),
    )

    assert response.status_code == 422
    assert "different scenarios" in response.json()["detail"]
