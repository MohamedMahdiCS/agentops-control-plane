"""Security regression tests for the Tool Gateway policy boundary."""

import pytest

from backend.app.services.tool_gateway import evaluate_request

INCIDENT = "INC-1042"


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("get_incident", {"incident_id": INCIDENT}),
        ("get_service_health", {"service_name": "payment-service"}),
        ("get_service_logs", {"service_name": "payment-service"}),
        ("get_service_metrics", {"service_name": "database"}),
        (
            "get_service_dependencies",
            {"service_name": "payment-service"},
        ),
    ],
)
def test_registered_diagnostic_tools_are_allowed(tool_name, arguments):
    decision = evaluate_request(tool_name, arguments, INCIDENT)

    assert decision.decision == "allow"
    assert decision.reason_code == "READ_ONLY_V1"
    assert decision.action == tool_name


@pytest.mark.parametrize(
    ("tool_name", "arguments", "reason"),
    [
        ("unknown_tool", {}, "UNKNOWN_TOOL"),
        (
            "get_incident",
            {"incident_id": "INC-9999"},
            "RESOURCE_OUT_OF_SCOPE",
        ),
        (
            "get_incident",
            {"incident_id": INCIDENT, "admin": True},
            "INVALID_ARGUMENTS",
        ),
        (
            "get_service_health",
            {"service_name": "payment-service", "approved": True},
            "INVALID_ARGUMENTS",
        ),
        (
            "get_service_logs",
            {
                "service_name": "payment-service",
                "lookback_minutes": 0,
            },
            "INVALID_ARGUMENTS",
        ),
        (
            "get_service_metrics",
            {"service_name": "unregistered-service"},
            "INVALID_ARGUMENTS",
        ),
        (
            "restart_service",
            {"service_name": "database", "reason": "short"},
            "INVALID_ARGUMENTS",
        ),
        (
            "restart_service",
            {
                "service_name": "payment-service",
                "reason": "Restart after investigating the incident.",
                "approved": True,
            },
            "INVALID_ARGUMENTS",
        ),
        (
            "get_service_health",
            "payment-service",
            "INVALID_ARGUMENTS",
        ),
    ],
)
def test_invalid_or_unauthorized_requests_fail_closed(tool_name, arguments, reason):
    decision = evaluate_request(tool_name, arguments, INCIDENT)

    assert decision.decision == "deny"
    assert decision.reason_code == reason
    assert decision.arguments == {}


def test_sensitive_tool_requires_operator_approval():
    decision = evaluate_request(
        "restart_service",
        {
            "service_name": "payment-service",
            "reason": "Restart after investigating database timeouts.",
        },
        INCIDENT,
    )

    assert decision.decision == "require_approval"
    assert decision.reason_code == "OPERATOR_APPROVAL_REQUIRED_V1"
    assert decision.action == "restart_service"
    assert decision.resource == "payment-service"


def test_agent_cannot_override_permission_with_approval_flag():
    decision = evaluate_request(
        "restart_service",
        {
            "service_name": "payment-service",
            "reason": "Restart after investigating database timeouts.",
            "approved": True,
            "admin": True,
        },
        INCIDENT,
    )

    assert decision.decision == "deny"
    assert decision.reason_code == "INVALID_ARGUMENTS"


def test_read_tool_arguments_are_validated_and_normalized():
    decision = evaluate_request(
        "get_service_logs",
        {"service_name": "payment-service"},
        INCIDENT,
    )

    assert decision.decision == "allow"
    assert decision.arguments["service_name"] == "payment-service"
    assert decision.arguments["lookback_minutes"] == 15


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("get_service_health", {"service_name": "payment-service"}),
        ("get_service_logs", {"service_name": "payment-service"}),
        ("get_service_metrics", {"service_name": "database"}),
        (
            "get_service_dependencies",
            {"service_name": "payment-service"},
        ),
        (
            "restart_service",
            {
                "service_name": "payment-service",
                "reason": "Investigate database connection failures.",
            },
        ),
    ],
)
def test_service_tools_deny_unknown_incident(tool_name, arguments):
    decision = evaluate_request(tool_name, arguments, "INC-9999")
    assert decision.decision == "deny"
    assert decision.reason_code == "RESOURCE_OUT_OF_SCOPE"
    assert decision.arguments == {}


def test_service_scope_excludes_unrelated_services(monkeypatch):
    from backend.app.simulator.scenarios import INCIDENTS

    isolated_incident = INCIDENTS[INCIDENT].model_copy(
        update={
            "incident_id": "INC-TEST",
            "affected_services": ["database"],
        }
    )
    monkeypatch.setitem(INCIDENTS, "INC-TEST", isolated_incident)

    allowed = evaluate_request(
        "get_service_health",
        {"service_name": "database"},
        "INC-TEST",
    )
    denied = evaluate_request(
        "get_service_health",
        {"service_name": "payment-service"},
        "INC-TEST",
    )

    assert allowed.decision == "allow"
    assert denied.decision == "deny"
    assert denied.reason_code == "RESOURCE_OUT_OF_SCOPE"


def test_transitive_incident_dependency_is_in_scope():
    decision = evaluate_request(
        "get_service_metrics",
        {"service_name": "database"},
        INCIDENT,
    )

    assert decision.decision == "allow"
