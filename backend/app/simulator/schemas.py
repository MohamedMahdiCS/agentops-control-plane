from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ServiceName = Literal[
    "order-service",
    "payment-service",
    "database",
]

HealthStatus = Literal["healthy", "degraded", "unhealthy"]
LogSeverity = Literal["DEBUG", "INFO", "WARN", "ERROR"]


class SimulatorModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )


class IncidentObservation(SimulatorModel):
    incident_id: str
    title: str
    description: str
    reported_at: datetime
    affected_services: list[ServiceName]


class ServiceHealthObservation(SimulatorModel):
    service_name: ServiceName
    status: HealthStatus
    message: str
    observed_at: datetime


class ServiceLogEntry(SimulatorModel):
    timestamp: datetime
    severity: LogSeverity
    message: str = Field(min_length=1)


class ServiceLogsObservation(SimulatorModel):
    service_name: ServiceName
    lookback_minutes: int = Field(ge=1, le=60)
    events: list[ServiceLogEntry]


class MetricReading(SimulatorModel):
    name: str = Field(min_length=1)
    value: float
    unit: str = Field(min_length=1)
    observed_at: datetime


class ServiceMetricsObservation(SimulatorModel):
    service_name: ServiceName
    metrics: list[MetricReading]


class ServiceDependenciesObservation(SimulatorModel):
    service_name: ServiceName
    dependencies: list[ServiceName]
