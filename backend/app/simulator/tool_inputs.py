from pydantic import Field

from backend.app.simulator.schemas import ServiceName, SimulatorModel


class GetIncidentInput(SimulatorModel):
    incident_id: str = Field(
        min_length=5,
        max_length=64,
        pattern=r"^INC-[A-Z0-9]+(?:-[A-Z0-9]+)*$",
    )


class GetServiceHealthInput(SimulatorModel):
    service_name: ServiceName


class GetServiceLogsInput(SimulatorModel):
    service_name: ServiceName
    lookback_minutes: int = Field(default=15, ge=1, le=60)


class GetServiceMetricsInput(SimulatorModel):
    service_name: ServiceName


class GetServiceDependenciesInput(SimulatorModel):
    service_name: ServiceName


class RestartServiceInput(SimulatorModel):
    service_name: ServiceName
    reason: str = Field(min_length=10, max_length=300)
