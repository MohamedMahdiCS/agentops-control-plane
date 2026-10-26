from datetime import UTC, datetime, timedelta

from backend.app.simulator.schemas import (
    IncidentObservation,
    MetricReading,
    ServiceDependenciesObservation,
    ServiceHealthObservation,
    ServiceLogEntry,
    ServiceName,
)

SCENARIO_TIME = datetime(2026, 10, 24, 6, 0, tzinfo=UTC)

INCIDENTS: dict[str, IncidentObservation] = {
    "INC-1042": IncidentObservation(
        incident_id="INC-1042",
        title="Elevated payment failures",
        description=(
            "Customers are experiencing increased payment failures "
            "and delayed order processing."
        ),
        reported_at=SCENARIO_TIME,
        affected_services=[
            "payment-service",
            "order-service",
        ],
    ),
}

SERVICE_HEALTH: dict[ServiceName, ServiceHealthObservation] = {
    "order-service": ServiceHealthObservation(
        service_name="order-service",
        status="degraded",
        message="Order completion rate is below normal.",
        observed_at=SCENARIO_TIME,
    ),
    "payment-service": ServiceHealthObservation(
        service_name="payment-service",
        status="degraded",
        message="Payment requests are experiencing timeouts.",
        observed_at=SCENARIO_TIME,
    ),
    "database": ServiceHealthObservation(
        service_name="database",
        status="degraded",
        message="Connection acquisition latency is elevated.",
        observed_at=SCENARIO_TIME,
    ),
}

SERVICE_DEPENDENCIES: dict[ServiceName, ServiceDependenciesObservation] = {
    "order-service": ServiceDependenciesObservation(
        service_name="order-service",
        dependencies=["payment-service"],
    ),
    "payment-service": ServiceDependenciesObservation(
        service_name="payment-service",
        dependencies=["database"],
    ),
    "database": ServiceDependenciesObservation(
        service_name="database",
        dependencies=[],
    ),
}


# Fixed observations for reproducible incident investigations.
# These records are evidence, not an authoritative root-cause answer.

SERVICE_LOGS: dict[ServiceName, list[ServiceLogEntry]] = {
    "order-service": [
        ServiceLogEntry(
            timestamp=SCENARIO_TIME - timedelta(minutes=8),
            severity="WARN",
            message="Checkout completion rate below expected baseline.",
        ),
        ServiceLogEntry(
            timestamp=SCENARIO_TIME - timedelta(minutes=3),
            severity="ERROR",
            message="Payment dependency request timed out.",
        ),
    ],
    "payment-service": [
        ServiceLogEntry(
            timestamp=SCENARIO_TIME - timedelta(minutes=10),
            severity="WARN",
            message="Database connection acquisition latency increasing.",
        ),
        ServiceLogEntry(
            timestamp=SCENARIO_TIME - timedelta(minutes=4),
            severity="ERROR",
            message="Timed out waiting for available database connection.",
        ),
    ],
    "database": [
        ServiceLogEntry(
            timestamp=SCENARIO_TIME - timedelta(minutes=12),
            severity="INFO",
            message="Database service responding to health probes.",
        ),
        ServiceLogEntry(
            timestamp=SCENARIO_TIME - timedelta(minutes=5),
            severity="WARN",
            message="Active connections approaching configured capacity.",
        ),
    ],
}


def reading(name: str, value: float, unit: str) -> MetricReading:
    return MetricReading(
        name=name,
        value=value,
        unit=unit,
        observed_at=SCENARIO_TIME - timedelta(minutes=1),
    )


SERVICE_METRICS: dict[ServiceName, list[MetricReading]] = {
    "order-service": [
        reading("checkout_error_rate", 12.4, "percent"),
        reading("request_p95_latency", 3200.0, "ms"),
    ],
    "payment-service": [
        reading("payment_error_rate", 18.7, "percent"),
        reading("request_p95_latency", 2850.0, "ms"),
        reading("database_connection_wait_p95", 1750.0, "ms"),
    ],
    "database": [
        reading("active_connections", 40.0, "connections"),
        reading("connection_capacity", 40.0, "connections"),
        reading("connection_acquisition_p95", 1680.0, "ms"),
    ],
}
