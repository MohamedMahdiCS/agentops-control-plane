"""HTTP security and contract tests for the benchmark API."""

import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.app.api.v1 import benchmarks
from backend.app.benchmark.manifest import ManifestStore
from backend.app.benchmark.runner import BenchmarkBusyError, BenchmarkConfigurationError
from backend.app.core import operator_auth
from tests.test_benchmark_analysis import manifest, outcome

TOKEN = "test-only-benchmark-token-" + "a" * 40
TOKEN_HASH = hashlib.sha256(TOKEN.encode()).hexdigest()


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr(
        operator_auth,
        "Settings",
        lambda: SimpleNamespace(
            operator_token_sha256=SecretStr(TOKEN_HASH),
            operator_id="trusted-benchmarker",
        ),
    )
    store = ManifestStore(tmp_path)
    state = {"calls": [], "error": None}

    class FakeRunner:
        def __init__(self, operator_id):
            self.operator_id = operator_id

        async def start(self, **kwargs):
            state["calls"].append(("start", self.operator_id, kwargs))
            if state["error"]:
                raise state["error"]
            return store.write(manifest(outcome("B01")))

        async def replay(self, benchmark_run_id, label=None):
            state["calls"].append(("replay", benchmark_run_id))
            source = store.load(benchmark_run_id)
            return store.write(
                manifest(*source.scenarios, replay_of=source.benchmark_run_id)
            )

        async def resume(self, benchmark_run_id):
            state["calls"].append(("resume", benchmark_run_id))
            return store.load(benchmark_run_id)

    app = FastAPI()
    app.include_router(benchmarks.router, prefix="/api/v1")

    def fake_store(principal: benchmarks.Operator):
        state["calls"].append(("store", principal.operator_id))
        return store

    def fake_runner(principal: benchmarks.Operator):
        return FakeRunner(principal.operator_id)

    app.dependency_overrides[benchmarks.get_manifest_store] = fake_store
    app.dependency_overrides[benchmarks.get_runner] = fake_runner

    with TestClient(app) as client:
        yield client, store, state


def auth(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/benchmarks"),
        ("post", "/api/v1/benchmarks"),
        ("get", f"/api/v1/benchmarks/{uuid4()}"),
        ("post", f"/api/v1/benchmarks/{uuid4()}/replay"),
        ("post", f"/api/v1/benchmarks/{uuid4()}/resume"),
        ("get", f"/api/v1/benchmarks/{uuid4()}/compare?baseline_id={uuid4()}"),
        ("get", f"/api/v1/benchmarks/{uuid4()}/report.md"),
    ],
)
def test_every_route_requires_operator(api, method, path):
    client, _, state = api
    kwargs = {"json": {"agent_id": str(uuid4())}} if method == "post" else {}

    assert getattr(client, method)(path, **kwargs).status_code == 401
    assert (
        getattr(client, method)(
            path, headers=auth("bad-" + "x" * 40), **kwargs
        ).status_code
        == 401
    )
    assert state["calls"] == []


def test_start_uses_server_operator_identity(api):
    client, _, state = api

    response = client.post(
        "/api/v1/benchmarks",
        json={"agent_id": str(uuid4()), "scenario_keys": ["B01"]},
        headers=auth() | {"X-Operator-ID": "attacker"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["manifest"]["gates"]["overall"]["status"] == "passed"
    assert response.json()["performance"]["scenarios_measured"] == 1
    start = next(call for call in state["calls"] if call[0] == "start")
    assert start[1] == "trusted-benchmarker"


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (BenchmarkBusyError("busy"), 409),
        (BenchmarkConfigurationError("Unknown scenario Z99"), 422),
    ],
)
def test_runner_errors_map_to_safe_responses(api, error, status_code):
    client, _, state = api
    state["error"] = error

    response = client.post(
        "/api/v1/benchmarks", json={"agent_id": str(uuid4())}, headers=auth()
    )

    assert response.status_code == status_code


def test_request_validation(api):
    client, _, _ = api

    for body in (
        {"agent_id": "nope"},
        {"agent_id": str(uuid4()), "scenario_keys": []},
        {"agent_id": str(uuid4()), "unexpected": True},
    ):
        response = client.post("/api/v1/benchmarks", json=body, headers=auth())
        assert response.status_code == 422


def test_list_detail_replay_compare_and_report(api):
    client, store, _ = api
    original = store.write(manifest(outcome("B01"), outcome("F01")))

    listing = client.get("/api/v1/benchmarks", headers=auth()).json()
    assert listing["benchmarks"][0]["benchmark_run_id"] == str(
        original.benchmark_run_id
    )
    assert listing["benchmarks"][0]["passed"] == 2

    replay = client.post(
        f"/api/v1/benchmarks/{original.benchmark_run_id}/replay",
        json={},
        headers=auth(),
    )
    assert replay.status_code == 201
    replay_id = replay.json()["manifest"]["benchmark_run_id"]

    comparison = client.get(
        f"/api/v1/benchmarks/{replay_id}/compare?baseline_id={original.benchmark_run_id}",
        headers=auth(),
    )
    assert comparison.status_code == 200
    assert comparison.json()["regression"] is False

    report = client.get(
        f"/api/v1/benchmarks/{replay_id}/report.md?baseline_id={original.benchmark_run_id}",
        headers=auth(),
    )
    assert report.status_code == 200
    assert report.headers["content-type"].startswith("text/markdown")
    assert "Comparison with" in report.text

    assert (
        client.get(f"/api/v1/benchmarks/{uuid4()}", headers=auth()).status_code == 404
    )


def test_corrupt_manifest_is_reported_not_served(api):
    client, store, _ = api
    written = store.write(manifest(outcome("B01")))
    path = store.path_for(written.benchmark_run_id)
    data = json.loads(path.read_text())
    data["label"] = "edited"
    path.write_text(json.dumps(data))

    listing = client.get("/api/v1/benchmarks", headers=auth()).json()
    detail = client.get(
        f"/api/v1/benchmarks/{written.benchmark_run_id}", headers=auth()
    )

    assert listing["corrupt_manifests"] == [str(written.benchmark_run_id)]
    assert detail.status_code == 409
