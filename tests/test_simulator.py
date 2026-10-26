import pytest
from pydantic import ValidationError

from backend.app.simulator.registry import (
    TOOLS,
    UnknownToolError,
    invoke_tool,
)
from backend.app.simulator.scenarios import (
    SCENARIO_TIME,
    SERVICE_HEALTH,
)
from backend.app.simulator.tools import ApprovalRequiredError


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("get_incident", {"incident_id": "INC-1042"}),
        ("get_service_health", {"service_name": "payment-service"}),
        (
            "get_service_logs",
            {"service_name": "payment-service", "lookback_minutes": 15},
        ),
        ("get_service_metrics", {"service_name": "database"}),
        ("get_service_dependencies", {"service_name": "payment-service"}),
    ],
)
def test_diagnostic_tools_return_validated_outputs(tool_name, arguments):
    definition = TOOLS[tool_name]

    assert definition.permission == "read"
    assert definition.output_schema is not None

    result = invoke_tool(tool_name, arguments)

    assert isinstance(result, definition.output_schema)
    assert result.model_dump() == invoke_tool(tool_name, arguments).model_dump()


def test_registry_has_five_read_tools_and_one_sensitive_tool():
    assert len(TOOLS) == 6
    assert sum(tool.permission == "read" for tool in TOOLS.values()) == 5
    assert TOOLS["restart_service"].permission == "require_approval"


def test_incident_observation_does_not_expose_ground_truth():
    incident = invoke_tool(
        "get_incident",
        {"incident_id": "INC-1042"},
    )
    payload = incident.model_dump()

    assert payload["incident_id"] == "INC-1042"
    assert "root_cause_code" not in payload
    assert "ground_truth" not in payload


def test_log_lookback_filters_evidence():
    result = invoke_tool(
        "get_service_logs",
        {"service_name": "payment-service", "lookback_minutes": 5},
    )

    assert len(result.events) == 1
    assert result.events[0].severity == "ERROR"
    assert all(event.timestamp <= SCENARIO_TIME for event in result.events)


def test_database_metrics_are_consistent():
    result = invoke_tool(
        "get_service_metrics",
        {"service_name": "database"},
    )
    values = {metric.name: metric.value for metric in result.metrics}

    assert values["active_connections"] == 40.0
    assert values["connection_capacity"] == 40.0


def test_dependency_graph_is_consistent():
    order = invoke_tool(
        "get_service_dependencies",
        {"service_name": "order-service"},
    )
    payment = invoke_tool(
        "get_service_dependencies",
        {"service_name": "payment-service"},
    )

    assert order.dependencies == ["payment-service"]
    assert payment.dependencies == ["database"]


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("get_service_health", {"service_name": "production-server"}),
        ("get_service_health", {"service_name": "database", "admin": True}),
        (
            "get_service_logs",
            {"service_name": "payment-service", "lookback_minutes": 0},
        ),
        (
            "get_service_logs",
            {"service_name": "payment-service", "lookback_minutes": 61},
        ),
        (
            "get_service_logs",
            {"service_name": "payment-service", "lookback_minutes": "15"},
        ),
    ],
)
def test_invalid_tool_arguments_are_rejected(name, arguments):
    with pytest.raises(ValidationError):
        invoke_tool(name, arguments)


def test_unknown_tool_is_rejected():
    with pytest.raises(UnknownToolError):
        invoke_tool("execute_shell", {"command": "anything"})


def test_unsupported_incident_is_rejected():
    with pytest.raises(ValueError, match="Unsupported incident"):
        invoke_tool("get_incident", {"incident_id": "INC-9999"})


def test_tool_output_cannot_change_source_fixture():
    original = SERVICE_HEALTH["payment-service"].model_dump()

    result = invoke_tool(
        "get_service_health",
        {"service_name": "payment-service"},
    )
    result.message = "Modified externally"

    assert SERVICE_HEALTH["payment-service"].model_dump() == original


def test_restart_requires_approval_without_modifying_service():
    original = SERVICE_HEALTH["payment-service"].model_dump()

    with pytest.raises(ApprovalRequiredError):
        invoke_tool(
            "restart_service",
            {
                "service_name": "payment-service",
                "reason": "Persistent payment processing timeouts.",
            },
        )

    assert SERVICE_HEALTH["payment-service"].model_dump() == original


def test_forged_restart_approval_is_rejected():
    with pytest.raises(ValidationError):
        invoke_tool(
            "restart_service",
            {
                "service_name": "payment-service",
                "reason": "Persistent payment processing timeouts.",
                "approved": True,
            },
        )
