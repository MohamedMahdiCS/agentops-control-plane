from collections.abc import Callable
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from backend.app.simulator.schemas import (
    IncidentObservation,
    ServiceDependenciesObservation,
    ServiceHealthObservation,
    ServiceLogsObservation,
    ServiceMetricsObservation,
    SimulatorModel,
)
from backend.app.simulator.tool_inputs import (
    GetIncidentInput,
    GetServiceDependenciesInput,
    GetServiceHealthInput,
    GetServiceLogsInput,
    GetServiceMetricsInput,
    RestartServiceInput,
)
from backend.app.simulator.tools import (
    ApprovalRequiredError,
    get_incident,
    get_service_dependencies,
    get_service_health,
    get_service_logs,
    get_service_metrics,
)

ToolPermission = Literal["read", "require_approval"]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    permission: ToolPermission
    input_schema: type[SimulatorModel]
    output_schema: type[SimulatorModel] | None


TOOLS = MappingProxyType(
    {
        "get_incident": ToolDefinition(
            "get_incident",
            "read",
            GetIncidentInput,
            IncidentObservation,
        ),
        "get_service_health": ToolDefinition(
            "get_service_health",
            "read",
            GetServiceHealthInput,
            ServiceHealthObservation,
        ),
        "get_service_logs": ToolDefinition(
            "get_service_logs",
            "read",
            GetServiceLogsInput,
            ServiceLogsObservation,
        ),
        "get_service_metrics": ToolDefinition(
            "get_service_metrics",
            "read",
            GetServiceMetricsInput,
            ServiceMetricsObservation,
        ),
        "get_service_dependencies": ToolDefinition(
            "get_service_dependencies",
            "read",
            GetServiceDependenciesInput,
            ServiceDependenciesObservation,
        ),
        "restart_service": ToolDefinition(
            "restart_service",
            "require_approval",
            RestartServiceInput,
            None,
        ),
    }
)


_READ_HANDLERS: dict[str, Callable[[dict[str, object]], SimulatorModel]] = {
    "get_incident": get_incident,
    "get_service_health": get_service_health,
    "get_service_logs": get_service_logs,
    "get_service_metrics": get_service_metrics,
    "get_service_dependencies": get_service_dependencies,
}


class UnknownToolError(ValueError):
    pass


def invoke_tool(
    name: str,
    arguments: dict[str, object],
) -> SimulatorModel:
    definition = TOOLS.get(name)

    if definition is None:
        raise UnknownToolError(f"Unknown tool: {name}")

    validated = definition.input_schema.model_validate(arguments)

    if definition.permission != "read":
        raise ApprovalRequiredError(
            "Sensitive tool execution is unavailable without "
            "verified policy and operator authorization."
        )

    handler = _READ_HANDLERS[name]
    result = handler(validated.model_dump())

    if definition.output_schema is None:
        raise RuntimeError("Missing tool output schema")

    return definition.output_schema.model_validate(result.model_dump())
