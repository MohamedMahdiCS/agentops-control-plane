"""Benchmark execution, replay and recovery against real worker runs.

Runs only against the isolated agentops_test database.
"""

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, func, insert, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from backend.app.benchmark.analysis import compare_benchmarks
from backend.app.benchmark.manifest import ManifestStore
from backend.app.benchmark.runner import (
    BenchmarkBusyError,
    BenchmarkRunner,
    runner_lock,
)
from backend.app.core.config import Settings
from backend.app.core.session import create_session_factory
from backend.app.models.agent import Agent
from backend.app.models.agent_run import AgentRun
from backend.app.models.approval_request import ApprovalRequest
from backend.app.models.audit_event import AuditEvent
from backend.app.models.evaluation_result import EvaluationResult
from backend.app.models.policy_decision import PolicyDecision
from backend.app.models.trace_span import TraceSpan


@pytest.fixture
def bench(tmp_path):
    if os.getenv("AGENTOPS_RUN_DB_INTEGRATION") != "1":
        pytest.skip("Database integration tests require activation")
    url = make_url(Settings().database_url.get_secret_value())
    if url.database != "agentops_test":
        pytest.fail("Refusing benchmark tests outside agentops_test")

    agent_id = uuid4()
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            insert(Agent).values(
                id=agent_id,
                name=f"Benchmark Test {agent_id.hex[:12]}",
                agent_type="incident_response",
                status="active",
                config_version=1,
                config_json={"environment": "test"},
            )
        )
    try:
        yield engine, agent_id, ManifestStore(tmp_path / "runs")
    finally:
        with engine.begin() as connection:
            run_ids = (
                connection.execute(
                    select(AgentRun.id).where(AgentRun.agent_id == agent_id)
                )
                .scalars()
                .all()
            )
            if run_ids:
                connection.execute(
                    update(AgentRun)
                    .where(AgentRun.id.in_(run_ids))
                    .values(pending_approval_id=None)
                )
                for model in (
                    EvaluationResult,
                    ApprovalRequest,
                    AuditEvent,
                    PolicyDecision,
                    TraceSpan,
                ):
                    connection.execute(delete(model).where(model.run_id.in_(run_ids)))
                connection.execute(delete(AgentRun).where(AgentRun.id.in_(run_ids)))
            connection.execute(delete(Agent).where(Agent.id == agent_id))
        engine.dispose()


def with_runner(store, callback):
    async def execute():
        engine = create_async_engine(Settings().database_url.get_secret_value())
        try:
            runner = BenchmarkRunner(
                create_session_factory(engine), store, operator_id="benchmark-test"
            )
            return await callback(runner)
        finally:
            await engine.dispose()

    return asyncio.run(execute())


def count_runs(engine, agent_id):
    with engine.connect() as connection:
        return connection.scalar(
            select(func.count()).where(AgentRun.agent_id == agent_id)
        )


def test_full_suite_executes_grades_and_gates(bench):
    engine, agent_id, store = bench

    manifest = with_runner(
        store, lambda r: r.start(agent_id=agent_id, label="CI suite")
    )

    assert manifest.status == "completed"
    outcomes = {s.scenario_key: s for s in manifest.scenarios}
    assert set(outcomes) == {"B01", "F01", "F02", "S02", "S03"}
    for outcome in outcomes.values():
        assert outcome.status == "completed", outcome
        assert outcome.verdict == "passed", outcome
        assert outcome.policy_gate_passed is True
        assert outcome.outcome_signature and outcome.performance
    assert outcomes["F02"].run_status == "failed"
    assert outcomes["F02"].error_code == "TOOL_RETRY_LIMIT"
    assert outcomes["S02"].error_code == "TOOL_POLICY_DENIED"
    assert outcomes["S02"].performance.denied_requests == 1
    assert outcomes["S03"].error_code == "APPROVAL_EXPIRED"
    assert outcomes["S03"].harness_notes
    assert manifest.gates.overall.status == "passed"

    # The stored manifest is sealed and every run is linked to the benchmark.
    reloaded = store.load(manifest.benchmark_run_id)
    assert reloaded.checksum == reloaded.computed_checksum()
    with engine.connect() as connection:
        linked = connection.scalar(
            select(func.count()).where(
                AgentRun.benchmark_run_id == manifest.benchmark_run_id
            )
        )
        executed_restarts = connection.scalar(
            select(func.count()).where(
                ApprovalRequest.run_id == outcomes["S03"].run_id,
                ApprovalRequest.execution_status == "executed",
            )
        )
    assert linked == 5
    assert executed_restarts == 0


def test_replay_reproduces_behaviour_without_regression(bench):
    _, agent_id, store = bench
    keys = ["B01", "F01", "S02"]

    original = with_runner(
        store, lambda r: r.start(agent_id=agent_id, scenario_keys=keys)
    )
    replay = with_runner(store, lambda r: r.replay(original.benchmark_run_id))

    assert replay.replay_of == original.benchmark_run_id
    assert replay.scenario_versions == original.scenario_versions
    comparison = compare_benchmarks(original, replay)
    assert comparison["regression"] is False
    assert comparison["fully_reproduced"] is True
    assert {row["scenario_key"] for row in comparison["scenarios"]} == set(keys)


def test_resume_is_idempotent_and_preserves_results(bench):
    engine, agent_id, store = bench
    first = with_runner(
        store, lambda r: r.start(agent_id=agent_id, scenario_keys=["B01", "F02"])
    )
    runs_before = count_runs(engine, agent_id)

    # Simulate a crash after the database work for B01 but before its
    # manifest update was recorded.
    interrupted = first.model_copy(
        update={
            "status": "interrupted",
            "scenarios": [
                first.scenarios[0].model_copy(
                    update={"status": "running", "verdict": None, "evaluation_id": None}
                ),
                first.scenarios[1],
            ],
        }
    )
    store.write(interrupted)

    resumed = with_runner(store, lambda r: r.resume(first.benchmark_run_id))

    assert count_runs(engine, agent_id) == runs_before
    recovered = resumed.scenarios[0]
    assert recovered.status == "completed"
    assert recovered.run_id == first.scenarios[0].run_id
    assert recovered.evaluation_id == first.scenarios[0].evaluation_id
    assert any("Reused existing run" in note for note in recovered.harness_notes)
    assert resumed.scenarios[1] == first.scenarios[1]


def test_concurrent_runner_is_rejected(bench):
    _, agent_id, store = bench

    with runner_lock(store.root), pytest.raises(BenchmarkBusyError):
        with_runner(store, lambda r: r.start(agent_id=agent_id, scenario_keys=["B01"]))
