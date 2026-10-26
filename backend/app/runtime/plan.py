from dataclasses import dataclass

from backend.app.simulator.faults import ReadToolName
from backend.app.simulator.registry import TOOLS

MAX_DIAGNOSTIC_CALLS = 10


@dataclass(frozen=True)
class DiagnosticStep:
    tool_name: ReadToolName
    arguments: dict[str, object]


REFERENCE_PLAN = (
    DiagnosticStep(
        "get_incident",
        {"incident_id": "INC-1042"},
    ),
    DiagnosticStep(
        "get_service_health",
        {"service_name": "payment-service"},
    ),
    DiagnosticStep(
        "get_service_dependencies",
        {"service_name": "payment-service"},
    ),
    DiagnosticStep(
        "get_service_logs",
        {
            "service_name": "payment-service",
            "lookback_minutes": 15,
        },
    ),
    DiagnosticStep(
        "get_service_metrics",
        {"service_name": "payment-service"},
    ),
    DiagnosticStep(
        "get_service_metrics",
        {"service_name": "database"},
    ),
    DiagnosticStep(
        "get_service_logs",
        {
            "service_name": "database",
            "lookback_minutes": 15,
        },
    ),
    DiagnosticStep(
        "get_service_health",
        {"service_name": "database"},
    ),
)


def plan_for_incident(
    incident_id: str,
) -> tuple[DiagnosticStep, ...]:
    if incident_id != "INC-1042":
        raise ValueError("Unsupported investigation incident")

    if len(REFERENCE_PLAN) > MAX_DIAGNOSTIC_CALLS:
        raise RuntimeError("Investigation exceeds tool-call budget")

    for step in REFERENCE_PLAN:
        definition = TOOLS[step.tool_name]

        if definition.permission != "read":
            raise RuntimeError("Sensitive tool in diagnostic plan")

        definition.input_schema.model_validate(step.arguments)

    return REFERENCE_PLAN
