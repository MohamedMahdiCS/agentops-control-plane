from datetime import timedelta

from backend.app.simulator.scenarios import (
    INCIDENTS,
    SCENARIO_TIME,
    SERVICE_DEPENDENCIES,
    SERVICE_HEALTH,
    SERVICE_LOGS,
    SERVICE_METRICS,
)
from backend.app.simulator.schemas import (
    IncidentObservation,
    ServiceDependenciesObservation,
    ServiceHealthObservation,
    ServiceLogsObservation,
    ServiceMetricsObservation,
)
from backend.app.simulator.tool_inputs import (
    GetIncidentInput,
    GetServiceDependenciesInput,
    GetServiceHealthInput,
    GetServiceLogsInput,
    GetServiceMetricsInput,
    RestartServiceInput,
)


def get_incident(arguments: dict[str, object]) -> IncidentObservation:
    request = GetIncidentInput.model_validate(arguments)

    incident = INCIDENTS.get(request.incident_id)
    if incident is None:
        raise ValueError("Unsupported incident identifier")

    return incident.model_copy(deep=True)


def get_service_health(
    arguments: dict[str, object],
) -> ServiceHealthObservation:
    request = GetServiceHealthInput.model_validate(arguments)
    return SERVICE_HEALTH[request.service_name].model_copy(deep=True)


def get_service_logs(
    arguments: dict[str, object],
) -> ServiceLogsObservation:
    request = GetServiceLogsInput.model_validate(arguments)

    cutoff = SCENARIO_TIME - timedelta(minutes=request.lookback_minutes)

    events = [
        entry.model_copy(deep=True)
        for entry in SERVICE_LOGS[request.service_name]
        if cutoff <= entry.timestamp <= SCENARIO_TIME
    ]

    return ServiceLogsObservation(
        service_name=request.service_name,
        lookback_minutes=request.lookback_minutes,
        events=events,
    )


def get_service_metrics(
    arguments: dict[str, object],
) -> ServiceMetricsObservation:
    request = GetServiceMetricsInput.model_validate(arguments)

    return ServiceMetricsObservation(
        service_name=request.service_name,
        metrics=[
            metric.model_copy(deep=True)
            for metric in SERVICE_METRICS[request.service_name]
        ],
    )


def get_service_dependencies(
    arguments: dict[str, object],
) -> ServiceDependenciesObservation:
    request = GetServiceDependenciesInput.model_validate(arguments)

    return SERVICE_DEPENDENCIES[request.service_name].model_copy(deep=True)


class ApprovalRequiredError(PermissionError):
    """Sensitive operation blocked pending verified authorization."""


def restart_service(arguments: dict[str, object]) -> None:
    """Validate a synthetic restart request, then deny execution.

    Actual execution requires the future policy gateway,
    scoped operator approval, and idempotent effect recording.
    """
    RestartServiceInput.model_validate(arguments)

    raise ApprovalRequiredError(
        "Service restart requires verified operator approval; "
        "remediation execution is not implemented."
    )
