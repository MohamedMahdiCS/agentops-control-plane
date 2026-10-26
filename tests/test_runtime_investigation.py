import pytest

from backend.app.runtime.contracts import InvestigationCheckpoint
from backend.app.runtime.investigation import execute_next_step
from backend.app.runtime.plan import plan_for_incident
from backend.app.runtime.reporting import build_investigation_report
from backend.app.simulator.faults import (
    FaultInjectingSimulator,
    FaultSpec,
)

INCIDENT = "INC-1042"


def test_investigation_collects_eight_evidence_records():
    state = None

    for _ in plan_for_incident(INCIDENT):
        state = execute_next_step(INCIDENT, state)

    assert state.next_step == 8
    assert state.tool_calls_used == 8
    assert len(state.evidence) == 8
    assert not state.failed_attempts

    assert execute_next_step(INCIDENT, state) == state


def test_checkpoint_survives_serialization():
    state = execute_next_step(INCIDENT)

    restored = InvestigationCheckpoint.model_validate_json(state.model_dump_json())

    resumed = execute_next_step(INCIDENT, restored)

    assert resumed.next_step == 2
    assert resumed.tool_calls_used == 2
    assert len(resumed.evidence) == 2


def test_two_failures_then_successful_recovery():
    simulator = FaultInjectingSimulator(
        [
            FaultSpec(
                tool_name="get_incident",
                call_number=1,
                fault_type="timeout",
            ),
            FaultSpec(
                tool_name="get_incident",
                call_number=2,
                fault_type="rate_limit",
            ),
        ]
    )

    state = None

    for _ in range(3):
        state = execute_next_step(
            INCIDENT,
            state,
            tool_invoker=simulator.invoke,
        )

    assert state.next_step == 1
    assert state.tool_calls_used == 3
    assert len(state.failed_attempts) == 2
    assert len(state.evidence) == 1

    restored = InvestigationCheckpoint.model_validate_json(state.model_dump_json())

    assert restored == state


def test_retry_limit_blocks_fourth_attempt():
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

    state = None

    for _ in range(3):
        state = execute_next_step(
            INCIDENT,
            state,
            tool_invoker=simulator.invoke,
        )

    with pytest.raises(RuntimeError, match="retry limit"):
        execute_next_step(
            INCIDENT,
            state,
            tool_invoker=simulator.invoke,
        )


def test_overall_budget_blocks_eleventh_call():
    simulator = FaultInjectingSimulator(
        [
            FaultSpec(
                tool_name="get_incident",
                call_number=1,
                fault_type="timeout",
            ),
            FaultSpec(
                tool_name="get_incident",
                call_number=2,
                fault_type="timeout",
            ),
            FaultSpec(
                tool_name="get_service_health",
                call_number=1,
                fault_type="timeout",
            ),
        ]
    )

    state = None

    for _ in range(10):
        state = execute_next_step(
            INCIDENT,
            state,
            tool_invoker=simulator.invoke,
        )

    assert state.tool_calls_used == 10
    assert len(state.failed_attempts) == 3
    assert state.next_step == 7

    with pytest.raises(RuntimeError, match="budget exhausted"):
        execute_next_step(
            INCIDENT,
            state,
            tool_invoker=simulator.invoke,
        )


def test_malformed_tool_output_is_recorded():
    state = execute_next_step(
        INCIDENT,
        tool_invoker=lambda name, args: object(),
    )

    assert state.next_step == 0
    assert state.tool_calls_used == 1
    assert state.failed_attempts[0].error_code == ("INVALID_TOOL_RESULT")


def test_complete_evidence_produces_supported_diagnosis():
    state = None

    for _ in plan_for_incident(INCIDENT):
        state = execute_next_step(INCIDENT, state)

    report = build_investigation_report(INCIDENT, state)

    assert report.root_cause_code == ("DB_CONNECTION_POOL_EXHAUSTION")
    assert report.confidence == "high"

    collected_ids = {evidence.evidence_id for evidence in state.evidence}

    assert set(report.evidence_ids).issubset(collected_ids)


def test_partial_evidence_produces_uncertainty():
    state = execute_next_step(INCIDENT)
    report = build_investigation_report(INCIDENT, state)

    assert report.root_cause_code == "INSUFFICIENT_EVIDENCE"
    assert report.confidence == "insufficient"
    assert report.evidence_ids == ["E001"]


def test_zero_evidence_cannot_generate_report():
    state = InvestigationCheckpoint(
        next_step=0,
        tool_calls_used=0,
    )

    with pytest.raises(ValueError, match="without evidence"):
        build_investigation_report(INCIDENT, state)


def test_inconsistent_checkpoint_is_rejected():
    state = InvestigationCheckpoint(
        next_step=1,
        tool_calls_used=1,
        evidence=[],
    )

    with pytest.raises(ValueError, match="mismatch"):
        execute_next_step(INCIDENT, state)
