"""Evaluation engine integration tests against real worker-recorded evidence.

Runs only against the isolated agentops_test database.
"""

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, insert, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from backend.app.core.config import Settings
from backend.app.core.session import create_session_factory
from backend.app.evaluation.catalog import latest_scenario
from backend.app.models.agent import Agent
from backend.app.models.agent_run import AgentRun
from backend.app.models.approval_request import ApprovalRequest
from backend.app.models.audit_event import AuditEvent
from backend.app.models.evaluation_case import EvaluationCase
from backend.app.models.evaluation_result import EvaluationResult
from backend.app.models.policy_decision import PolicyDecision
from backend.app.models.trace_span import TraceSpan
from backend.app.runtime.contracts import InvestigationCheckpoint
from backend.app.runtime.runner import run_worker_once
from backend.app.services import evaluations as service
from backend.app.services.run_claims import claim_next_run
from backend.app.services.run_finalization import finalize_run
from backend.app.services.tool_gateway import GatewayDeniedError, ToolGateway
from backend.app.simulator.faults import FaultInjectingSimulator


@pytest.fixture
def database():
    if os.getenv("AGENTOPS_RUN_DB_INTEGRATION") != "1":
        pytest.skip("Database integration tests require activation")

    url = make_url(Settings().database_url.get_secret_value())
    if url.database != "agentops_test":
        pytest.fail("Refusing evaluation tests outside agentops_test")

    agent_id = uuid4()
    engine = create_engine(url)
    run_ids: list = []

    with engine.begin() as connection:
        connection.execute(
            insert(Agent).values(
                id=agent_id,
                name=f"Evaluation Test {agent_id.hex[:12]}",
                agent_type="incident_response",
                status="active",
                config_version=1,
                config_json={"environment": "test"},
            )
        )

    def new_run():
        run_id = uuid4()
        with engine.begin() as connection:
            connection.execute(
                insert(AgentRun).values(
                    id=run_id,
                    agent_id=agent_id,
                    incident_id="INC-1042",
                    status="queued",
                    agent_config_version=1,
                    agent_config_snapshot={"environment": "test"},
                    execution_mode="deterministic",
                )
            )
        run_ids.append(run_id)
        return run_id

    try:
        yield SimpleDatabase(engine, new_run)
    finally:
        with engine.begin() as connection:
            for run_id in run_ids:
                connection.execute(
                    update(AgentRun)
                    .where(AgentRun.id == run_id)
                    .values(pending_approval_id=None)
                )
                for model in (
                    EvaluationResult,
                    ApprovalRequest,
                    AuditEvent,
                    PolicyDecision,
                    TraceSpan,
                ):
                    connection.execute(delete(model).where(model.run_id == run_id))
                connection.execute(delete(AgentRun).where(AgentRun.id == run_id))
            connection.execute(delete(Agent).where(Agent.id == agent_id))
            connection.execute(
                delete(EvaluationCase).where(EvaluationCase.scenario_key == "Z98")
            )
        engine.dispose()


class SimpleDatabase:
    def __init__(self, engine, new_run):
        self.engine = engine
        self.new_run = new_run


async def with_factory(callback):
    engine = create_async_engine(Settings().database_url.get_secret_value())
    try:
        return await callback(create_session_factory(engine))
    finally:
        await engine.dispose()


def run_worker(run_id, faults=()):
    async def execute(factory):
        options = {}
        if faults:
            options["tool_invoker"] = FaultInjectingSimulator(list(faults)).invoke
        return await run_worker_once(
            factory, worker_id="evaluation-test-worker", run_id=run_id, **options
        )

    return asyncio.run(with_factory(execute))


def evaluate(run_id, scenario_key, idempotency_key=None):
    async def execute(factory):
        async with factory() as session:
            return await service.evaluate_run(
                session,
                run_id=run_id,
                scenario_key=scenario_key,
                scenario_version=None,
                operator_id="integration-operator",
                idempotency_key=idempotency_key,
            )

    return asyncio.run(with_factory(execute))


def test_worker_run_is_graded_from_its_own_evidence(database):
    run_id = database.new_run()
    assert run_worker(run_id).finalized is True

    recorded = evaluate(run_id, "B01")
    result = recorded.result

    assert recorded.created is True
    assert result.status == "completed"
    assert result.verdict == "passed"
    assert result.score == 100
    assert result.policy_gate_passed is True
    assert result.case_version == 1
    assert result.grader_version == 1

    with database.engine.connect() as connection:
        run_spans = set(
            connection.execute(select(TraceSpan.id).where(TraceSpan.run_id == run_id))
            .scalars()
            .all()
        )
        audit = connection.execute(
            select(AuditEvent.actor_type, AuditEvent.actor_identifier).where(
                AuditEvent.run_id == run_id,
                AuditEvent.event_type == "evaluation.recorded",
                AuditEvent.resource_id == str(result.id),
            )
        ).one()

    assert result.evidence_span_ids
    assert set(result.evidence_span_ids) <= run_spans
    assert audit.actor_type == "operator"
    assert audit.actor_identifier == "integration-operator"


def test_regrading_is_reproducible_and_appends_history(database):
    run_id = database.new_run()
    run_worker(run_id)

    first = evaluate(run_id, "B01").result
    second = evaluate(run_id, "B01").result

    assert first.id != second.id
    assert first.score == second.score
    assert first.verdict == second.verdict
    assert (
        first.criteria_results["evidence_fingerprint"]
        == second.criteria_results["evidence_fingerprint"]
    )

    async def history(factory):
        async with factory() as session:
            rows = await service.list_evaluations(session, run_id=run_id)
            comparison = await service.compare_stored_evaluations(
                session, first.id, second.id
            )
            return rows, comparison

    rows, comparison = asyncio.run(with_factory(history))
    assert [result.id for result, _ in rows] == [second.id, first.id]
    assert comparison["regression"] is False
    assert comparison["same_evidence"] is True


def test_idempotency_key_replays_and_rejects_reuse(database):
    run_id = database.new_run()
    other_run = database.new_run()
    run_worker(run_id)
    run_worker(other_run)
    key = f"eval-{uuid4()}"

    first = evaluate(run_id, "B01", key)
    replay = evaluate(run_id, "B01", key)

    assert first.created is True
    assert replay.created is False
    assert replay.result.id == first.result.id

    with pytest.raises(service.EvaluationIdempotencyConflictError):
        evaluate(other_run, "B01", key)


def test_fault_scenarios_grade_real_recovery_and_safe_stop(database):
    recovered = database.new_run()
    stopped = database.new_run()
    run_worker(recovered, latest_scenario("F01").scenario_config.faults)
    run_worker(stopped, latest_scenario("F02").scenario_config.faults)

    recovery = evaluate(recovered, "F01").result
    safe_stop = evaluate(stopped, "F02").result
    baseline_on_stop = evaluate(stopped, "B01").result

    assert recovery.verdict == "passed"
    assert recovery.criteria_results["metrics"]["failed_attempts"] == 1
    assert safe_stop.verdict == "passed"
    assert baseline_on_stop.verdict == "failed"
    assert baseline_on_stop.policy_gate_passed is True

    healthy = database.new_run()
    run_worker(healthy)
    healthy_result = evaluate(healthy, "B01").result

    async def compare(factory):
        async with factory() as session:
            return await service.compare_stored_evaluations(
                session, healthy_result.id, baseline_on_stop.id
            )

    comparison = asyncio.run(with_factory(compare))
    assert comparison["regression"] is True
    assert comparison["verdict_change"] == "regressed"


def test_gateway_denial_is_credited_as_working_safeguard(database):
    run_id = database.new_run()

    async def deny_and_stop(factory):
        async with factory() as session:
            claim = await claim_next_run(
                session, worker_id="evaluation-deny-worker", run_id=run_id
            )
        gateway = ToolGateway(factory, claim)
        with pytest.raises(GatewayDeniedError):
            await gateway.invoke(
                "delete_database",
                {"service_name": "database"},
                checkpoint=InvestigationCheckpoint(next_step=0, tool_calls_used=0),
                active_elapsed_ms=0,
            )
        # Mirrors the worker's handling of a gateway denial.
        async with factory() as session:
            return await finalize_run(
                session,
                claim,
                status="failed",
                error_code="TOOL_POLICY_DENIED",
                result_summary="Investigation stopped safely.",
            )

    assert asyncio.run(with_factory(deny_and_stop)) is True

    security = evaluate(run_id, "S02").result
    baseline = evaluate(run_id, "B01").result

    assert security.verdict == "passed"
    assert security.policy_gate_passed is True
    assert security.criteria_results["metrics"]["denied_requests"] == 1
    assert baseline.verdict == "failed"
    assert baseline.policy_gate_passed is True


def test_non_terminal_run_is_rejected_without_recording(database):
    run_id = database.new_run()

    with pytest.raises(service.RunNotTerminalError):
        evaluate(run_id, "B01")

    with database.engine.connect() as connection:
        stored = connection.execute(
            select(EvaluationResult.id).where(EvaluationResult.run_id == run_id)
        ).all()
    assert stored == []


def test_catalog_rejects_modified_published_version(database):
    original = latest_scenario("B01").model_copy(update={"scenario_key": "Z98"})
    modified = original.model_copy(
        update={
            "scenario_config": original.scenario_config.model_copy(
                update={"description": "A silently edited published scenario."}
            )
        }
    )

    async def sync(factory, scenarios):
        async with factory() as session:
            return await service.sync_catalog(session, scenarios)

    created = asyncio.run(with_factory(lambda f: sync(f, (original,))))
    verified = asyncio.run(with_factory(lambda f: sync(f, (original,))))
    assert (created.created, created.verified) == (1, 0)
    assert (verified.created, verified.verified) == (0, 1)

    with pytest.raises(service.CatalogIntegrityError):
        asyncio.run(with_factory(lambda f: sync(f, (modified,))))


def test_overview_counts_only_stored_results(database):
    run_id = database.new_run()
    run_worker(run_id)
    evaluate(run_id, "B01")

    async def overview(factory):
        async with factory() as session:
            return await service.evaluation_overview(session)

    summary = asyncio.run(with_factory(overview))
    baseline = next(s for s in summary.scenarios if s.case.scenario_key == "B01")

    assert summary.total >= 1
    assert summary.total == summary.passed + summary.failed + summary.inconclusive
    assert baseline.total >= 1
    assert baseline.latest is not None
