import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, insert, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from backend.app.core.config import Settings
from backend.app.core.session import create_session_factory
from backend.app.models.agent import Agent
from backend.app.models.agent_run import AgentRun
from backend.app.models.approval_request import ApprovalRequest
from backend.app.models.audit_event import AuditEvent
from backend.app.models.policy_decision import PolicyDecision
from backend.app.models.trace_span import TraceSpan
from backend.app.services.run_checkpoints import save_run_checkpoint
from backend.app.services.run_claims import claim_next_run
from backend.app.services.run_finalization import finalize_run


@pytest.fixture
def isolated_run():
    if os.getenv("AGENTOPS_RUN_DB_INTEGRATION") != "1":
        pytest.skip("Database integration tests require activation")

    url = make_url(Settings().database_url.get_secret_value())

    if url.database != "agentops_test":
        pytest.fail("Refusing worker tests outside agentops_test")

    agent_id = uuid4()
    run_id = uuid4()
    engine = create_engine(url)

    try:
        with engine.begin() as connection:
            connection.execute(
                insert(Agent).values(
                    id=agent_id,
                    name=f"Worker Test {agent_id.hex[:12]}",
                    agent_type="incident_response",
                    status="active",
                    config_version=1,
                    config_json={"environment": "test"},
                )
            )

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

        yield run_id, engine

    finally:
        with engine.begin() as connection:
            connection.execute(
                update(AgentRun)
                .where(AgentRun.id == run_id)
                .values(pending_approval_id=None)
            )
            for model in (ApprovalRequest, AuditEvent, PolicyDecision, TraceSpan):
                connection.execute(delete(model).where(model.run_id == run_id))
            connection.execute(delete(AgentRun).where(AgentRun.id == run_id))
            connection.execute(delete(Agent).where(Agent.id == agent_id))

        engine.dispose()


async def claim_with_worker(run_id, worker_id):
    engine = create_async_engine(Settings().database_url.get_secret_value())

    try:
        factory = create_session_factory(engine)

        async with factory() as session:
            return await claim_next_run(
                session,
                worker_id=worker_id,
                lease_seconds=60,
                run_id=run_id,
            )
    finally:
        await engine.dispose()


def test_claim_persists_worker_ownership(isolated_run):
    run_id, engine = isolated_run

    claim = asyncio.run(claim_with_worker(run_id, "worker-alpha"))

    assert claim is not None
    assert claim.run_id == run_id
    assert claim.worker_id == "worker-alpha"
    assert claim.lease_generation == 1
    assert claim.attempt_count == 1
    assert claim.agent_config_snapshot == {"environment": "test"}

    with engine.connect() as connection:
        saved = connection.execute(
            select(
                AgentRun.status,
                AgentRun.lease_owner,
                AgentRun.lease_generation,
                AgentRun.attempt_count,
            ).where(AgentRun.id == run_id)
        ).one()

    assert saved.status == "running"
    assert saved.lease_owner == "worker-alpha"
    assert saved.lease_generation == 1
    assert saved.attempt_count == 1

    second_claim = asyncio.run(claim_with_worker(run_id, "worker-beta"))
    assert second_claim is None


def test_concurrent_workers_have_single_winner(isolated_run):
    run_id, _ = isolated_run

    async def compete():
        return await asyncio.gather(
            claim_with_worker(run_id, "worker-one"),
            claim_with_worker(run_id, "worker-two"),
        )

    results = asyncio.run(compete())
    winners = [result for result in results if result is not None]

    assert len(winners) == 1
    assert winners[0].lease_generation == 1
    assert winners[0].attempt_count == 1


def test_expired_lease_can_be_reclaimed(isolated_run):
    run_id, engine = isolated_run

    first = asyncio.run(claim_with_worker(run_id, "original-worker"))
    assert first is not None

    with engine.begin() as connection:
        connection.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id)
            .values(lease_expires_at=(datetime.now(UTC) - timedelta(minutes=1)))
        )

    recovered = asyncio.run(claim_with_worker(run_id, "recovery-worker"))

    assert recovered is not None
    assert recovered.worker_id == "recovery-worker"
    assert recovered.lease_generation == 2
    assert recovered.attempt_count == 2
    assert recovered.run_id == first.run_id


async def save_checkpoint_for_claim(claim, checkpoint, elapsed_ms):
    engine = create_async_engine(Settings().database_url.get_secret_value())
    try:
        factory = create_session_factory(engine)
        async with factory() as session:
            return await save_run_checkpoint(session, claim, checkpoint, elapsed_ms)
    finally:
        await engine.dispose()


def test_checkpoint_persists_progress(isolated_run):
    run_id, engine = isolated_run
    claim = asyncio.run(claim_with_worker(run_id, "worker-alpha"))
    assert claim is not None

    saved = asyncio.run(
        save_checkpoint_for_claim(claim, {"step": 1, "tool_calls": 2}, 120)
    )
    assert saved is True

    saved_again = asyncio.run(
        save_checkpoint_for_claim(claim, {"step": 2, "tool_calls": 3}, 100)
    )
    assert saved_again is True

    with engine.connect() as connection:
        row = connection.execute(
            select(
                AgentRun.execution_checkpoint,
                AgentRun.active_elapsed_ms,
            ).where(AgentRun.id == run_id)
        ).one()

    assert row.execution_checkpoint == {
        "step": 2,
        "tool_calls": 3,
    }
    assert row.active_elapsed_ms == 120


def test_expired_worker_cannot_save_checkpoint(isolated_run):
    run_id, engine = isolated_run
    claim = asyncio.run(claim_with_worker(run_id, "worker-alpha"))
    assert claim is not None

    with engine.begin() as connection:
        connection.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id)
            .values(lease_expires_at=(datetime.now(UTC) - timedelta(minutes=1)))
        )

    saved = asyncio.run(save_checkpoint_for_claim(claim, {"step": 99}, 500))
    assert saved is False

    with engine.connect() as connection:
        checkpoint = connection.execute(
            select(AgentRun.execution_checkpoint).where(AgentRun.id == run_id)
        ).scalar_one()

    assert checkpoint is None


def test_recovered_worker_fences_stale_checkpoint(isolated_run):
    run_id, engine = isolated_run

    original = asyncio.run(claim_with_worker(run_id, "original-worker"))
    assert original is not None

    with engine.begin() as connection:
        connection.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id)
            .values(lease_expires_at=(datetime.now(UTC) - timedelta(minutes=1)))
        )

    recovered = asyncio.run(claim_with_worker(run_id, "recovery-worker"))
    assert recovered is not None
    assert recovered.lease_generation == 2

    assert (
        asyncio.run(save_checkpoint_for_claim(original, {"step": "stale"}, 900))
        is False
    )

    assert (
        asyncio.run(save_checkpoint_for_claim(recovered, {"step": "recovered"}, 250))
        is True
    )

    with engine.connect() as connection:
        checkpoint = connection.execute(
            select(AgentRun.execution_checkpoint).where(AgentRun.id == run_id)
        ).scalar_one()

    assert checkpoint == {"step": "recovered"}


async def finalize_for_claim(claim, **kwargs):
    engine = create_async_engine(Settings().database_url.get_secret_value())

    try:
        factory = create_session_factory(engine)

        async with factory() as session:
            return await finalize_run(session, claim, **kwargs)
    finally:
        await engine.dispose()


def test_run_completion_is_persisted(isolated_run):
    run_id, engine = isolated_run
    claim = asyncio.run(claim_with_worker(run_id, "worker-alpha"))
    assert claim is not None

    result = asyncio.run(
        finalize_for_claim(
            claim,
            status="completed",
            result_summary="Investigation completed successfully.",
            active_elapsed_ms=500,
        )
    )
    assert result is True

    with engine.connect() as connection:
        saved = connection.execute(
            select(
                AgentRun.status,
                AgentRun.finished_at,
                AgentRun.result_summary,
                AgentRun.error_code,
                AgentRun.lease_owner,
                AgentRun.lease_expires_at,
                AgentRun.active_elapsed_ms,
            ).where(AgentRun.id == run_id)
        ).one()

    assert saved.status == "completed"
    assert saved.finished_at is not None
    assert saved.result_summary == "Investigation completed successfully."
    assert saved.error_code is None
    assert saved.lease_owner is None
    assert saved.lease_expires_at is None
    assert saved.active_elapsed_ms == 500


def test_run_failure_is_persisted(isolated_run):
    run_id, engine = isolated_run
    claim = asyncio.run(claim_with_worker(run_id, "worker-alpha"))
    assert claim is not None

    result = asyncio.run(
        finalize_for_claim(
            claim,
            status="failed",
            error_code="TOOL_TIMEOUT",
            result_summary="Diagnostic tool exceeded its timeout.",
            active_elapsed_ms=750,
        )
    )
    assert result is True

    with engine.connect() as connection:
        saved = connection.execute(
            select(
                AgentRun.status,
                AgentRun.finished_at,
                AgentRun.result_summary,
                AgentRun.error_code,
                AgentRun.lease_owner,
                AgentRun.lease_expires_at,
                AgentRun.active_elapsed_ms,
            ).where(AgentRun.id == run_id)
        ).one()

    assert saved.status == "failed"
    assert saved.error_code == "TOOL_TIMEOUT"
    assert saved.finished_at is not None
    assert saved.lease_owner is None


def test_completed_run_cannot_be_finalized_twice(isolated_run):
    run_id, _ = isolated_run
    claim = asyncio.run(claim_with_worker(run_id, "worker-alpha"))
    assert claim is not None

    first = asyncio.run(
        finalize_for_claim(
            claim,
            status="completed",
            result_summary="First and final result.",
        )
    )
    assert first is True

    second = asyncio.run(
        finalize_for_claim(
            claim,
            status="failed",
            error_code="LATE_ERROR",
        )
    )
    assert second is False


def test_stale_worker_cannot_finalize_recovered_run(isolated_run):
    run_id, engine = isolated_run

    original = asyncio.run(claim_with_worker(run_id, "original-worker"))
    assert original is not None

    with engine.begin() as connection:
        connection.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id)
            .values(lease_expires_at=(datetime.now(UTC) - timedelta(minutes=1)))
        )

    recovered = asyncio.run(claim_with_worker(run_id, "recovery-worker"))
    assert recovered is not None

    stale_result = asyncio.run(
        finalize_for_claim(
            original,
            status="completed",
            result_summary="Stale worker result.",
        )
    )
    assert stale_result is False

    valid_result = asyncio.run(
        finalize_for_claim(
            recovered,
            status="completed",
            result_summary="Recovered worker result.",
        )
    )
    assert valid_result is True

    with engine.connect() as connection:
        saved_summary = connection.execute(
            select(AgentRun.result_summary).where(AgentRun.id == run_id)
        ).scalar_one()

    assert saved_summary == "Recovered worker result."


# End-to-end deterministic worker integration tests.

from backend.app.runtime.runner import run_worker_once
from backend.app.simulator.faults import FaultInjectingSimulator, FaultSpec


async def execute_test_worker_cycle(run_id, tool_invoker=None):
    engine = create_async_engine(Settings().database_url.get_secret_value())

    try:
        factory = create_session_factory(engine)
        options = {"run_id": run_id}

        if tool_invoker is not None:
            options["tool_invoker"] = tool_invoker

        return await run_worker_once(
            factory,
            worker_id="integration-test-worker",
            **options,
        )
    finally:
        await engine.dispose()


def test_worker_completes_investigation_end_to_end(isolated_run):
    run_id, engine = isolated_run

    result = asyncio.run(execute_test_worker_cycle(run_id))

    assert result.run_id == run_id
    assert result.finalized is True

    with engine.connect() as connection:
        saved = connection.execute(
            select(
                AgentRun.status,
                AgentRun.result_summary,
                AgentRun.error_code,
                AgentRun.execution_checkpoint,
                AgentRun.finished_at,
                AgentRun.lease_owner,
            ).where(AgentRun.id == run_id)
        ).one()

    assert saved.status == "completed"
    assert saved.error_code is None
    assert saved.finished_at is not None
    assert saved.lease_owner is None

    assert "database connection" in saved.result_summary.lower()

    checkpoint = saved.execution_checkpoint
    assert checkpoint["next_step"] == 8
    assert checkpoint["tool_calls_used"] == 8
    assert len(checkpoint["evidence"]) == 8

    assert [item["evidence_id"] for item in checkpoint["evidence"]] == [
        f"E{i:03d}" for i in range(1, 9)
    ]


def test_worker_records_retry_exhaustion_end_to_end(isolated_run):
    run_id, engine = isolated_run

    simulator = FaultInjectingSimulator(
        [
            FaultSpec(
                tool_name="get_incident",
                call_number=number,
                fault_type="timeout",
            )
            for number in (1, 2, 3)
        ]
    )

    result = asyncio.run(
        execute_test_worker_cycle(
            run_id,
            tool_invoker=simulator.invoke,
        )
    )

    assert result.run_id == run_id
    assert result.finalized is True

    with engine.connect() as connection:
        saved = connection.execute(
            select(
                AgentRun.status,
                AgentRun.error_code,
                AgentRun.execution_checkpoint,
            ).where(AgentRun.id == run_id)
        ).one()

    assert saved.status == "failed"
    assert saved.error_code == "TOOL_RETRY_LIMIT"

    checkpoint = saved.execution_checkpoint
    assert checkpoint["next_step"] == 0
    assert checkpoint["tool_calls_used"] == 3
    assert len(checkpoint["failed_attempts"]) == 3


def test_worker_does_not_reexecute_completed_run(isolated_run):
    run_id, _ = isolated_run

    first = asyncio.run(execute_test_worker_cycle(run_id))
    assert first.finalized is True

    second = asyncio.run(execute_test_worker_cycle(run_id))

    assert second.run_id is None
    assert second.finalized is False


def test_worker_resumes_after_interrupted_investigation(isolated_run):
    from backend.app.runtime.investigation import execute_next_step
    from backend.app.simulator.registry import invoke_tool

    run_id, engine = isolated_run

    # Worker A claims the job and persists its first observation.
    original = asyncio.run(claim_with_worker(run_id, "interrupted-worker"))
    assert original is not None

    first_checkpoint = execute_next_step("INC-1042")
    assert first_checkpoint.next_step == 1

    saved = asyncio.run(
        save_checkpoint_for_claim(
            original,
            first_checkpoint.model_dump(mode="json"),
            2500,
        )
    )
    assert saved is True

    # Simulate a crashed worker whose lease has expired.
    with engine.begin() as connection:
        connection.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id)
            .values(lease_expires_at=(datetime.now(UTC) - timedelta(minutes=1)))
        )

    # Track diagnostic calls made by the replacement worker.
    executed_tools = []

    def tracking_invoker(name, arguments):
        executed_tools.append(name)
        return invoke_tool(name, arguments)

    result = asyncio.run(
        execute_test_worker_cycle(
            run_id,
            tool_invoker=tracking_invoker,
        )
    )

    assert result.run_id == run_id
    assert result.finalized is True

    with engine.connect() as connection:
        saved_run = connection.execute(
            select(
                AgentRun.status,
                AgentRun.execution_checkpoint,
                AgentRun.active_elapsed_ms,
                AgentRun.lease_generation,
                AgentRun.attempt_count,
                AgentRun.result_summary,
            ).where(AgentRun.id == run_id)
        ).one()

    assert saved_run.status == "completed"
    assert saved_run.lease_generation == 2
    assert saved_run.attempt_count == 2

    checkpoint = saved_run.execution_checkpoint
    assert checkpoint["next_step"] == 8
    assert checkpoint["tool_calls_used"] == 8
    assert len(checkpoint["evidence"]) == 8

    # The first tool was already completed before interruption.
    assert len(executed_tools) == 7
    assert "get_incident" not in executed_tools

    # Preserve the active execution time consumed before recovery.
    assert saved_run.active_elapsed_ms >= 2500

    assert "database connection" in saved_run.result_summary.lower()


# Lease-renewal integration tests.

from backend.app.services.run_leases import renew_run_lease


async def renew_for_claim(claim, lease_seconds=180):
    engine = create_async_engine(Settings().database_url.get_secret_value())
    try:
        factory = create_session_factory(engine)
        async with factory() as session:
            return await renew_run_lease(
                session,
                claim,
                lease_seconds=lease_seconds,
            )
    finally:
        await engine.dispose()


def test_active_worker_can_renew_lease(isolated_run):
    run_id, engine = isolated_run

    claim = asyncio.run(claim_with_worker(run_id, "worker-alpha"))
    assert claim is not None

    renewed = asyncio.run(renew_for_claim(claim, lease_seconds=180))
    assert renewed is True

    with engine.connect() as connection:
        saved_expiration = connection.execute(
            select(AgentRun.lease_expires_at).where(AgentRun.id == run_id)
        ).scalar_one()

    assert saved_expiration > claim.lease_expires_at


def test_expired_lease_cannot_be_renewed(isolated_run):
    run_id, engine = isolated_run

    claim = asyncio.run(claim_with_worker(run_id, "worker-alpha"))
    assert claim is not None

    with engine.begin() as connection:
        connection.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id)
            .values(lease_expires_at=(datetime.now(UTC) - timedelta(minutes=1)))
        )

    renewed = asyncio.run(renew_for_claim(claim))
    assert renewed is False


def test_stale_worker_cannot_renew_after_recovery(isolated_run):
    run_id, engine = isolated_run

    original = asyncio.run(claim_with_worker(run_id, "original-worker"))
    assert original is not None

    with engine.begin() as connection:
        connection.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id)
            .values(lease_expires_at=(datetime.now(UTC) - timedelta(minutes=1)))
        )

    recovered = asyncio.run(claim_with_worker(run_id, "recovery-worker"))
    assert recovered is not None
    assert recovered.lease_generation == 2

    assert asyncio.run(renew_for_claim(original)) is False
    assert asyncio.run(renew_for_claim(recovered)) is True


def test_worker_tool_timeout_fails_safely(
    isolated_run,
    monkeypatch,
):
    import time

    import backend.app.runtime.worker as worker_module
    from backend.app.simulator.registry import invoke_tool

    run_id, engine = isolated_run

    # Short timeout for testing; production remains at 15 seconds.
    monkeypatch.setattr(
        worker_module,
        "STEP_TIMEOUT_SECONDS",
        0.02,
    )

    executed_tools = []

    def slow_tool_invoker(name, arguments):
        executed_tools.append(name)
        time.sleep(0.15)
        return invoke_tool(name, arguments)

    result = asyncio.run(
        execute_test_worker_cycle(
            run_id,
            tool_invoker=slow_tool_invoker,
        )
    )

    assert result.run_id == run_id
    assert result.finalized is True

    with engine.connect() as connection:
        saved = connection.execute(
            select(
                AgentRun.status,
                AgentRun.error_code,
                AgentRun.finished_at,
                AgentRun.lease_owner,
                AgentRun.execution_checkpoint,
            ).where(AgentRun.id == run_id)
        ).one()

    assert saved.status == "failed"
    assert saved.error_code == "TOOL_STEP_TIMEOUT"
    assert saved.finished_at is not None
    assert saved.lease_owner is None

    # The timed-out observation must not be saved as evidence.
    checkpoint = saved.execution_checkpoint
    assert not checkpoint or not checkpoint.get("evidence")

    # The worker must not schedule further diagnostic steps.
    assert executed_tools == ["get_incident"]


# Day 9: Tool Gateway authorization and audit integration tests.

from backend.app.runtime.contracts import InvestigationCheckpoint
from backend.app.services.tool_gateway import (
    GatewayApprovalRequired,
    GatewayDeniedError,
    ToolGateway,
)
from backend.app.simulator.registry import invoke_tool


async def call_gateway_for_claim(
    claim,
    name,
    arguments,
    *,
    read_invoker=invoke_tool,
):
    async_engine = create_async_engine(Settings().database_url.get_secret_value())
    try:
        factory = create_session_factory(async_engine)
        gateway = ToolGateway(
            factory,
            claim,
            read_invoker=read_invoker,
        )
        return await gateway.invoke(
            name,
            arguments,
            checkpoint=InvestigationCheckpoint(next_step=0, tool_calls_used=0),
            active_elapsed_ms=0,
        )
    finally:
        await async_engine.dispose()


def test_gateway_authorizes_and_audits_read_tool(isolated_run):
    run_id, engine = isolated_run
    claim = asyncio.run(claim_with_worker(run_id, "gateway-read-worker"))
    assert claim is not None

    calls = []

    def tracked_invoker(name, arguments):
        calls.append(name)
        return invoke_tool(name, arguments)

    observation = asyncio.run(
        call_gateway_for_claim(
            claim,
            "get_incident",
            {"incident_id": "INC-1042"},
            read_invoker=tracked_invoker,
        )
    )

    assert observation.incident_id == "INC-1042"
    assert calls == ["get_incident"]

    with engine.connect() as connection:
        decision = connection.execute(
            select(
                PolicyDecision.decision,
                PolicyDecision.reason_code,
                PolicyDecision.executed,
            ).where(PolicyDecision.run_id == run_id)
        ).one()
        events = (
            connection.execute(
                select(AuditEvent.event_type).where(AuditEvent.run_id == run_id)
            )
            .scalars()
            .all()
        )

    assert decision.decision == "allow"
    assert decision.reason_code == "READ_ONLY_V1"
    assert decision.executed is True
    assert "tool.authorization" in events
    assert "tool.outcome" in events


def test_gateway_denies_and_audits_unknown_tool(isolated_run):
    run_id, engine = isolated_run
    claim = asyncio.run(claim_with_worker(run_id, "gateway-deny-worker"))
    assert claim is not None

    calls = []

    def tracked_invoker(name, arguments):
        calls.append(name)
        return invoke_tool(name, arguments)

    with pytest.raises(GatewayDeniedError):
        asyncio.run(
            call_gateway_for_claim(
                claim,
                "unknown_tool",
                {},
                read_invoker=tracked_invoker,
            )
        )

    assert calls == []

    with engine.connect() as connection:
        decision = connection.execute(
            select(
                PolicyDecision.decision,
                PolicyDecision.reason_code,
                PolicyDecision.executed,
            ).where(PolicyDecision.run_id == run_id)
        ).one()
        events = (
            connection.execute(
                select(AuditEvent.event_type).where(AuditEvent.run_id == run_id)
            )
            .scalars()
            .all()
        )

    assert decision.decision == "deny"
    assert decision.reason_code == "UNKNOWN_TOOL"
    assert decision.executed is False
    assert "tool.authorization" in events
    assert "tool.outcome" not in events


def test_gateway_creates_approval_without_execution(isolated_run):
    run_id, engine = isolated_run
    claim = asyncio.run(claim_with_worker(run_id, "gateway-approval-worker"))
    assert claim is not None

    calls = []

    def tracked_invoker(name, arguments):
        calls.append(name)
        return invoke_tool(name, arguments)

    with pytest.raises(GatewayApprovalRequired):
        asyncio.run(
            call_gateway_for_claim(
                claim,
                "restart_service",
                {
                    "service_name": "payment-service",
                    "reason": "Investigate database connection failures.",
                },
                read_invoker=tracked_invoker,
            )
        )

    assert calls == []

    with engine.connect() as connection:
        run = connection.execute(
            select(
                AgentRun.status,
                AgentRun.pending_approval_id,
                AgentRun.lease_owner,
            ).where(AgentRun.id == run_id)
        ).one()

        approval = connection.execute(
            select(
                ApprovalRequest.action,
                ApprovalRequest.status,
                ApprovalRequest.execution_status,
            ).where(ApprovalRequest.run_id == run_id)
        ).one()

        decision = connection.execute(
            select(
                PolicyDecision.decision,
                PolicyDecision.executed,
            ).where(PolicyDecision.run_id == run_id)
        ).one()

        events = (
            connection.execute(
                select(AuditEvent.event_type).where(AuditEvent.run_id == run_id)
            )
            .scalars()
            .all()
        )

    assert run.status == "awaiting_approval"
    assert run.pending_approval_id is not None
    assert run.lease_owner is None

    assert approval.action == "restart_service"
    assert approval.status == "pending"
    assert approval.execution_status == "not_started"

    assert decision.decision == "require_approval"
    assert decision.executed is False

    assert "tool.authorization" in events
    assert "tool.approval_requested" in events


# Day 9: Failure auditing and stale-worker security regression tests.

from backend.app.services.tool_gateway import (
    GatewayOwnershipError,
    InvalidToolResultError,
)


def test_gateway_rejects_mismatched_observation_and_audits(isolated_run):
    run_id, engine = isolated_run
    claim = asyncio.run(claim_with_worker(run_id, "gateway-validation-worker"))
    assert claim is not None

    def mismatched_invoker(name, arguments):
        result = invoke_tool(name, arguments)
        return result.model_copy(update={"incident_id": "INC-9999"})

    with pytest.raises(InvalidToolResultError):
        asyncio.run(
            call_gateway_for_claim(
                claim,
                "get_incident",
                {"incident_id": "INC-1042"},
                read_invoker=mismatched_invoker,
            )
        )

    with engine.connect() as connection:
        decision = connection.execute(
            select(PolicyDecision.executed).where(PolicyDecision.run_id == run_id)
        ).scalar_one()

        outcome = connection.execute(
            select(TraceSpan.safe_summary).where(TraceSpan.run_id == run_id)
        ).scalar_one()

        events = (
            connection.execute(
                select(AuditEvent.event_type).where(AuditEvent.run_id == run_id)
            )
            .scalars()
            .all()
        )

    assert decision is True
    assert outcome == "INVALID_TOOL_RESULT"
    assert "tool.authorization" in events
    assert "tool.outcome" in events


def test_gateway_persists_audit_after_unexpected_tool_failure(isolated_run):
    run_id, engine = isolated_run
    claim = asyncio.run(claim_with_worker(run_id, "gateway-failure-worker"))
    assert claim is not None

    secret_message = "PRIVATE_TOOL_ERROR_DETAILS"

    def failing_invoker(name, arguments):
        raise RuntimeError(secret_message)

    with pytest.raises(RuntimeError, match=secret_message):
        asyncio.run(
            call_gateway_for_claim(
                claim,
                "get_incident",
                {"incident_id": "INC-1042"},
                read_invoker=failing_invoker,
            )
        )

    with engine.connect() as connection:
        outcome = connection.execute(
            select(TraceSpan.safe_summary).where(TraceSpan.run_id == run_id)
        ).scalar_one()

        events = connection.execute(
            select(
                AuditEvent.event_type,
                AuditEvent.event_payload,
            ).where(AuditEvent.run_id == run_id)
        ).all()

    assert outcome == "TOOL_ERROR"

    event_types = [event.event_type for event in events]
    assert "tool.authorization" in event_types
    assert "tool.outcome" in event_types

    # Raw exception details must never enter persistent audit records.
    assert secret_message not in repr(events)


def test_gateway_rejects_expired_worker_without_dispatch(isolated_run):
    run_id, engine = isolated_run
    claim = asyncio.run(claim_with_worker(run_id, "gateway-expired-worker"))
    assert claim is not None

    with engine.begin() as connection:
        connection.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id)
            .values(lease_expires_at=(datetime.now(UTC) - timedelta(minutes=1)))
        )

    calls = []

    def tracked_invoker(name, arguments):
        calls.append(name)
        return invoke_tool(name, arguments)

    with pytest.raises(GatewayOwnershipError):
        asyncio.run(
            call_gateway_for_claim(
                claim,
                "get_incident",
                {"incident_id": "INC-1042"},
                read_invoker=tracked_invoker,
            )
        )

    assert calls == []

    with engine.connect() as connection:
        decisions = connection.execute(
            select(PolicyDecision.id).where(PolicyDecision.run_id == run_id)
        ).all()

    assert decisions == []


def test_worker_audits_every_diagnostic_before_dispatch(isolated_run):
    """The full investigation must never bypass gateway authorization."""
    run_id, engine = isolated_run
    dispatched = []

    def verified_invoker(name, arguments):
        # This callback runs only after the gateway commits authorization.
        with engine.connect() as connection:
            decisions = connection.execute(
                select(
                    PolicyDecision.action,
                    PolicyDecision.decision,
                ).where(PolicyDecision.run_id == run_id)
            ).all()

            authorization_events = connection.execute(
                select(AuditEvent.id).where(
                    AuditEvent.run_id == run_id,
                    AuditEvent.event_type == "tool.authorization",
                )
            ).all()

        expected_count = len(dispatched) + 1

        assert len(decisions) == expected_count
        assert len(authorization_events) == expected_count
        assert all(item.decision == "allow" for item in decisions)

        dispatched.append(name)
        return invoke_tool(name, arguments)

    result = asyncio.run(
        execute_test_worker_cycle(
            run_id,
            tool_invoker=verified_invoker,
        )
    )

    assert result.run_id == run_id
    assert result.finalized is True
    assert len(dispatched) == 8

    with engine.connect() as connection:
        run = connection.execute(
            select(
                AgentRun.status,
                AgentRun.execution_checkpoint,
            ).where(AgentRun.id == run_id)
        ).one()

        decisions = connection.execute(
            select(
                PolicyDecision.decision,
                PolicyDecision.executed,
            ).where(PolicyDecision.run_id == run_id)
        ).all()

        spans = connection.execute(
            select(
                TraceSpan.status,
                TraceSpan.safe_summary,
            ).where(
                TraceSpan.run_id == run_id,
                TraceSpan.span_type == "tool_call",
            )
        ).all()

        events = (
            connection.execute(
                select(AuditEvent.event_type).where(AuditEvent.run_id == run_id)
            )
            .scalars()
            .all()
        )

        approvals = connection.execute(
            select(ApprovalRequest.id).where(ApprovalRequest.run_id == run_id)
        ).all()

    assert run.status == "completed"
    assert run.execution_checkpoint["tool_calls_used"] == 8

    assert len(decisions) == 8
    assert all(item.decision == "allow" and item.executed is True for item in decisions)

    assert len(spans) == 8
    assert all(item.status == "ok" and item.safe_summary == "SUCCESS" for item in spans)

    assert events.count("tool.authorization") == 8
    assert events.count("tool.outcome") == 8
    assert approvals == []


def test_gateway_timeout_records_unknown_completion(isolated_run):
    """A timed-out thread must not be reported as never dispatched."""
    import time

    run_id, engine = isolated_run
    claim = asyncio.run(claim_with_worker(run_id, "gateway-timeout-worker"))
    assert claim is not None

    dispatched = []

    def slow_invoker(name, arguments):
        dispatched.append(name)
        time.sleep(0.15)
        return invoke_tool(name, arguments)

    async def invoke_with_short_timeout():
        async_engine = create_async_engine(Settings().database_url.get_secret_value())
        try:
            factory = create_session_factory(async_engine)
            gateway = ToolGateway(
                factory,
                claim,
                read_invoker=slow_invoker,
            )
            return await gateway.invoke(
                "get_incident",
                {"incident_id": "INC-1042"},
                checkpoint=InvestigationCheckpoint(
                    next_step=0,
                    tool_calls_used=0,
                ),
                active_elapsed_ms=0,
                timeout_seconds=0.02,
            )
        finally:
            await async_engine.dispose()

    with pytest.raises(TimeoutError):
        asyncio.run(invoke_with_short_timeout())

    assert dispatched == ["get_incident"]

    with engine.connect() as connection:
        decision = connection.execute(
            select(
                PolicyDecision.decision,
                PolicyDecision.executed,
            ).where(PolicyDecision.run_id == run_id)
        ).one()

        span = connection.execute(
            select(
                TraceSpan.status,
                TraceSpan.safe_summary,
            ).where(TraceSpan.run_id == run_id)
        ).one()

        events = connection.execute(
            select(
                AuditEvent.event_type,
                AuditEvent.event_payload,
            ).where(AuditEvent.run_id == run_id)
        ).all()

    assert decision.decision == "allow"
    assert decision.executed is True

    assert span.status == "error"
    assert span.safe_summary == "TOOL_TIMEOUT_UNKNOWN_COMPLETION"

    outcomes = [
        event.event_payload["outcome"]
        for event in events
        if event.event_type == "tool.outcome"
    ]

    assert outcomes == ["TOOL_TIMEOUT_UNKNOWN_COMPLETION"]
    assert any(event.event_type == "tool.authorization" for event in events)


# Day 9: Durable human-approval decision integration tests.

from backend.app.services.approval_decisions import (
    ApprovalConflictError,
    decide_pending_approval,
)


def create_pending_test_approval(run_id, engine):
    claim = asyncio.run(claim_with_worker(run_id, "approval-test-worker"))
    assert claim is not None

    with pytest.raises(GatewayApprovalRequired):
        asyncio.run(
            call_gateway_for_claim(
                claim,
                "restart_service",
                {
                    "service_name": "payment-service",
                    "reason": "Investigate persistent database connection failures.",
                },
            )
        )

    with engine.connect() as connection:
        return connection.execute(
            select(ApprovalRequest.id).where(ApprovalRequest.run_id == run_id)
        ).scalar_one()


async def decide_test_approval(approval_id, decision, key):
    async_engine = create_async_engine(Settings().database_url.get_secret_value())
    try:
        factory = create_session_factory(async_engine)
        async with factory() as session:
            return await decide_pending_approval(
                session,
                approval_id,
                decision=decision,
                operator_id="test-operator",
                reason="Reviewed the incident evidence and operational risks.",
                idempotency_key=key,
            )
    finally:
        await async_engine.dispose()


def test_approval_records_decision_without_executing(isolated_run):
    run_id, engine = isolated_run
    approval_id = create_pending_test_approval(run_id, engine)

    result = asyncio.run(
        decide_test_approval(approval_id, "approved", "approve-key-001")
    )

    assert result.status == "approved"
    assert result.run_status == "awaiting_approval"
    assert result.idempotent is False

    with engine.connect() as connection:
        approval = connection.execute(
            select(
                ApprovalRequest.status,
                ApprovalRequest.execution_status,
                ApprovalRequest.decided_by,
            ).where(ApprovalRequest.id == approval_id)
        ).one()

        run_status = connection.execute(
            select(AgentRun.status).where(AgentRun.id == run_id)
        ).scalar_one()

    assert approval.status == "approved"
    assert approval.execution_status == "not_started"
    assert approval.decided_by == "test-operator"
    assert run_status == "awaiting_approval"


def test_approval_retry_is_idempotent(isolated_run):
    run_id, engine = isolated_run
    approval_id = create_pending_test_approval(run_id, engine)

    first = asyncio.run(
        decide_test_approval(approval_id, "approved", "approve-key-002")
    )
    second = asyncio.run(
        decide_test_approval(approval_id, "approved", "approve-key-002")
    )

    assert first.idempotent is False
    assert second.idempotent is True

    with engine.connect() as connection:
        decision_events = connection.execute(
            select(AuditEvent.id).where(
                AuditEvent.run_id == run_id,
                AuditEvent.event_type == "approval.decided",
            )
        ).all()

    assert len(decision_events) == 1


def test_rejection_fails_run_without_execution(isolated_run):
    run_id, engine = isolated_run
    approval_id = create_pending_test_approval(run_id, engine)

    result = asyncio.run(
        decide_test_approval(approval_id, "rejected", "reject-key-001")
    )

    assert result.status == "rejected"
    assert result.run_status == "failed"

    with engine.connect() as connection:
        run = connection.execute(
            select(
                AgentRun.status,
                AgentRun.error_code,
                AgentRun.pending_approval_id,
            ).where(AgentRun.id == run_id)
        ).one()

        execution_status = connection.execute(
            select(ApprovalRequest.execution_status).where(
                ApprovalRequest.id == approval_id
            )
        ).scalar_one()

    assert run.status == "failed"
    assert run.error_code == "APPROVAL_REJECTED"
    assert run.pending_approval_id is None
    assert execution_status == "skipped"


def test_expired_approval_cannot_be_approved(isolated_run):
    run_id, engine = isolated_run
    approval_id = create_pending_test_approval(run_id, engine)

    with engine.begin() as connection:
        connection.execute(
            update(ApprovalRequest)
            .where(ApprovalRequest.id == approval_id)
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )

    result = asyncio.run(
        decide_test_approval(approval_id, "approved", "expired-key-001")
    )

    assert result.status == "expired"
    assert result.run_status == "failed"

    with engine.connect() as connection:
        run_error = connection.execute(
            select(AgentRun.error_code).where(AgentRun.id == run_id)
        ).scalar_one()

        execution_status = connection.execute(
            select(ApprovalRequest.execution_status).where(
                ApprovalRequest.id == approval_id
            )
        ).scalar_one()

    assert run_error == "APPROVAL_EXPIRED"
    assert execution_status == "skipped"


def test_conflicting_approval_retry_is_rejected(isolated_run):
    run_id, engine = isolated_run
    approval_id = create_pending_test_approval(run_id, engine)

    asyncio.run(decide_test_approval(approval_id, "approved", "approve-key-003"))

    with pytest.raises(ApprovalConflictError):
        asyncio.run(decide_test_approval(approval_id, "rejected", "reject-key-003"))


# Day 10: Automatic approval expiration integration tests.

from backend.app.services.approval_expiration import expire_pending_approvals


async def run_approval_expiration(*, concurrent=False):
    async_engine = create_async_engine(Settings().database_url.get_secret_value())
    try:
        factory = create_session_factory(async_engine)

        if concurrent:
            return await asyncio.gather(
                expire_pending_approvals(factory),
                expire_pending_approvals(factory),
            )

        return await expire_pending_approvals(factory)
    finally:
        await async_engine.dispose()


def set_test_approval_expired(approval_id, engine):
    with engine.begin() as connection:
        connection.execute(
            update(ApprovalRequest)
            .where(ApprovalRequest.id == approval_id)
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )


def test_automatic_expiration_is_durable_and_idempotent(isolated_run):
    run_id, engine = isolated_run
    approval_id = create_pending_test_approval(run_id, engine)
    set_test_approval_expired(approval_id, engine)

    first = asyncio.run(run_approval_expiration())
    second = asyncio.run(run_approval_expiration())

    assert first == 1
    assert second == 0

    with engine.connect() as connection:
        approval = connection.execute(
            select(
                ApprovalRequest.status,
                ApprovalRequest.execution_status,
            ).where(ApprovalRequest.id == approval_id)
        ).one()

        run = connection.execute(
            select(
                AgentRun.status,
                AgentRun.error_code,
                AgentRun.pending_approval_id,
            ).where(AgentRun.id == run_id)
        ).one()

        events = connection.execute(
            select(AuditEvent.id).where(
                AuditEvent.run_id == run_id,
                AuditEvent.event_type == "approval.expired",
            )
        ).all()

    assert approval.status == "expired"
    assert approval.execution_status == "skipped"
    assert run.status == "failed"
    assert run.error_code == "APPROVAL_EXPIRED"
    assert run.pending_approval_id is None
    assert len(events) == 1


def test_automatic_expiration_preserves_valid_pending_request(isolated_run):
    run_id, engine = isolated_run
    approval_id = create_pending_test_approval(run_id, engine)

    count = asyncio.run(run_approval_expiration())

    assert count == 0

    with engine.connect() as connection:
        status = connection.execute(
            select(ApprovalRequest.status).where(ApprovalRequest.id == approval_id)
        ).scalar_one()

        run_status = connection.execute(
            select(AgentRun.status).where(AgentRun.id == run_id)
        ).scalar_one()

    assert status == "pending"
    assert run_status == "awaiting_approval"


def test_automatic_expiration_preserves_approved_request(isolated_run):
    run_id, engine = isolated_run
    approval_id = create_pending_test_approval(run_id, engine)

    asyncio.run(
        decide_test_approval(
            approval_id,
            "approved",
            "approval-recovery-001",
        )
    )

    set_test_approval_expired(approval_id, engine)

    count = asyncio.run(run_approval_expiration())

    assert count == 0

    with engine.connect() as connection:
        status = connection.execute(
            select(ApprovalRequest.status).where(ApprovalRequest.id == approval_id)
        ).scalar_one()

        run_status = connection.execute(
            select(AgentRun.status).where(AgentRun.id == run_id)
        ).scalar_one()

    assert status == "approved"
    assert run_status == "awaiting_approval"


def test_concurrent_expiration_workers_process_request_once(isolated_run):
    run_id, engine = isolated_run
    approval_id = create_pending_test_approval(run_id, engine)
    set_test_approval_expired(approval_id, engine)

    counts = asyncio.run(run_approval_expiration(concurrent=True))

    assert sum(counts) == 1

    with engine.connect() as connection:
        events = connection.execute(
            select(AuditEvent.id).where(
                AuditEvent.run_id == run_id,
                AuditEvent.event_type == "approval.expired",
            )
        ).all()

        status = connection.execute(
            select(ApprovalRequest.status).where(ApprovalRequest.id == approval_id)
        ).scalar_one()

    assert status == "expired"
    assert len(events) == 1
