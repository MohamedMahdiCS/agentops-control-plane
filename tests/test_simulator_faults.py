import pytest
from pydantic import ValidationError

from backend.app.simulator.faults import (
    FaultInjectingSimulator,
    FaultSpec,
    SimulatedRateLimitError,
    SimulatedToolError,
)
from backend.app.simulator.registry import UnknownToolError
from backend.app.simulator.tools import ApprovalRequiredError


def test_timeout_occurs_on_configured_call():
    simulator = FaultInjectingSimulator(
        [
            FaultSpec(
                tool_name="get_service_metrics",
                call_number=2,
                fault_type="timeout",
            ),
        ]
    )
    arguments = {"service_name": "database"}

    first = simulator.invoke("get_service_metrics", arguments)

    with pytest.raises(TimeoutError):
        simulator.invoke("get_service_metrics", arguments)

    third = simulator.invoke("get_service_metrics", arguments)

    assert third.model_dump() == first.model_dump()


@pytest.mark.parametrize(
    ("fault_type", "expected_error"),
    [
        ("rate_limit", SimulatedRateLimitError),
        ("tool_error", SimulatedToolError),
        ("timeout", TimeoutError),
    ],
)
def test_injected_failures_recover(fault_type, expected_error):
    simulator = FaultInjectingSimulator(
        [
            FaultSpec(
                tool_name="get_service_health",
                call_number=1,
                fault_type=fault_type,
            ),
        ]
    )
    arguments = {"service_name": "payment-service"}

    with pytest.raises(expected_error):
        simulator.invoke("get_service_health", arguments)

    result = simulator.invoke("get_service_health", arguments)

    assert result.status == "degraded"


def test_reset_reproduces_failure_sequence():
    simulator = FaultInjectingSimulator(
        [
            FaultSpec(
                tool_name="get_service_logs",
                call_number=1,
                fault_type="rate_limit",
            ),
        ]
    )
    arguments = {"service_name": "payment-service"}

    with pytest.raises(SimulatedRateLimitError):
        simulator.invoke("get_service_logs", arguments)

    first_success = simulator.invoke("get_service_logs", arguments)

    simulator.reset()

    with pytest.raises(SimulatedRateLimitError):
        simulator.invoke("get_service_logs", arguments)

    replay_success = simulator.invoke("get_service_logs", arguments)

    assert replay_success.model_dump() == first_success.model_dump()


def test_simulator_instances_have_independent_counters():
    fault = FaultSpec(
        tool_name="get_incident",
        call_number=1,
        fault_type="timeout",
    )
    first = FaultInjectingSimulator([fault])
    second = FaultInjectingSimulator([fault])
    arguments = {"incident_id": "INC-1042"}

    with pytest.raises(TimeoutError):
        first.invoke("get_incident", arguments)

    with pytest.raises(TimeoutError):
        second.invoke("get_incident", arguments)

    assert first.invoke("get_incident", arguments).incident_id == "INC-1042"
    assert second.invoke("get_incident", arguments).incident_id == "INC-1042"


def test_duplicate_fault_specification_rejected():
    fault = FaultSpec(
        tool_name="get_incident",
        call_number=1,
        fault_type="timeout",
    )

    with pytest.raises(ValueError, match="Duplicate fault"):
        FaultInjectingSimulator([fault, fault])


@pytest.mark.parametrize(
    "arguments",
    [
        {
            "tool_name": "restart_service",
            "call_number": 1,
            "fault_type": "timeout",
        },
        {
            "tool_name": "get_incident",
            "call_number": 0,
            "fault_type": "timeout",
        },
        {
            "tool_name": "get_incident",
            "call_number": 1,
            "fault_type": "unknown",
        },
        {
            "tool_name": "get_incident",
            "call_number": "1",
            "fault_type": "timeout",
        },
    ],
)
def test_invalid_fault_specs_rejected(arguments):
    with pytest.raises(ValidationError):
        FaultSpec.model_validate(arguments)


def test_invalid_arguments_do_not_consume_fault():
    simulator = FaultInjectingSimulator(
        [
            FaultSpec(
                tool_name="get_service_health",
                call_number=1,
                fault_type="timeout",
            ),
        ]
    )

    with pytest.raises(ValidationError):
        simulator.invoke(
            "get_service_health",
            {"service_name": "production-server"},
        )

    with pytest.raises(TimeoutError):
        simulator.invoke(
            "get_service_health",
            {"service_name": "payment-service"},
        )


def test_unknown_tools_remain_blocked():
    simulator = FaultInjectingSimulator()

    with pytest.raises(UnknownToolError):
        simulator.invoke("execute_shell", {"command": "anything"})


def test_sensitive_tools_remain_blocked():
    simulator = FaultInjectingSimulator()

    with pytest.raises(ApprovalRequiredError):
        simulator.invoke(
            "restart_service",
            {
                "service_name": "payment-service",
                "reason": "Persistent payment processing timeouts.",
            },
        )


def test_forged_approval_is_rejected():
    simulator = FaultInjectingSimulator()

    with pytest.raises(ValidationError):
        simulator.invoke(
            "restart_service",
            {
                "service_name": "payment-service",
                "reason": "Persistent payment processing timeouts.",
                "approved": True,
            },
        )
