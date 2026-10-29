import json

from backend.app.runtime.contracts import (
    InvestigationCheckpoint,
    InvestigationReport,
)
from backend.app.runtime.plan import plan_for_incident
from backend.app.simulator.registry import TOOLS


def build_investigation_report(
    incident_id: str,
    checkpoint: InvestigationCheckpoint,
) -> InvestigationReport:
    """Infer a result from validated diagnostic observations."""
    plan = plan_for_incident(incident_id)

    if not checkpoint.evidence:
        raise ValueError("Cannot generate an investigation report without evidence")

    if checkpoint.next_step != len(checkpoint.evidence):
        raise ValueError("Inconsistent investigation checkpoint")

    if checkpoint.next_step > len(plan):
        raise ValueError("Checkpoint exceeds investigation plan")

    observations = {}

    for index, evidence in enumerate(checkpoint.evidence):
        expected = plan[index]

        if (
            evidence.tool_name != expected.tool_name
            or evidence.arguments != expected.arguments
            or evidence.evidence_id != f"E{index + 1:03d}"
        ):
            raise ValueError("Invalid evidence sequence")

        definition = TOOLS[evidence.tool_name]
        if definition.output_schema is None:
            raise ValueError("Missing observation schema")

        validated = definition.output_schema.model_validate_json(
            json.dumps(evidence.observation)
        )

        expected_resource = evidence.arguments.get(
            "service_name", evidence.arguments.get("incident_id")
        )
        actual_resource = getattr(
            validated,
            "service_name",
            getattr(validated, "incident_id", None),
        )

        if actual_resource != expected_resource:
            raise ValueError("Observation resource mismatch")

        observations[(evidence.tool_name, expected_resource)] = (
            evidence.evidence_id,
            validated,
        )

    def observed(tool_name, resource):
        return observations.get((tool_name, resource))

    dependencies = observed("get_service_dependencies", "payment-service")
    payment_logs = observed("get_service_logs", "payment-service")
    payment_metrics = observed("get_service_metrics", "payment-service")
    database_metrics = observed("get_service_metrics", "database")

    confirmed_ids = []

    if all(
        (
            dependencies,
            payment_logs,
            payment_metrics,
            database_metrics,
        )
    ):
        dependency_id, dependency_data = dependencies
        logs_id, logs_data = payment_logs
        payment_id, payment_data = payment_metrics
        database_id, database_data = database_metrics

        payment_values = {
            reading.name: reading.value for reading in payment_data.metrics
        }
        database_values = {
            reading.name: reading.value for reading in database_data.metrics
        }

        active = database_values.get("active_connections", 0)
        capacity = database_values.get("connection_capacity", 0)
        wait_ms = payment_values.get("database_connection_wait_p95", 0)

        dependency_confirmed = "database" in dependency_data.dependencies
        timeout_confirmed = any(
            "database" in event.message.lower()
            and (
                "connection" in event.message.lower()
                or "timeout" in event.message.lower()
            )
            for event in logs_data.events
        )
        capacity_confirmed = capacity > 0 and active >= capacity * 0.95
        waiting_confirmed = wait_ms >= 1000

        if all(
            (
                dependency_confirmed,
                timeout_confirmed,
                capacity_confirmed,
                waiting_confirmed,
            )
        ):
            confirmed_ids = [
                dependency_id,
                logs_id,
                payment_id,
                database_id,
            ]

            return InvestigationReport(
                incident_id=incident_id,
                root_cause_code="DB_CONNECTION_POOL_EXHAUSTION",
                diagnosis=(
                    "Payment-service database connection waits "
                    "coincide with near-saturation of the database "
                    "connection pool, corroborated by dependency "
                    "and timeout evidence."
                ),
                confidence="high",
                evidence_ids=confirmed_ids,
                recommendation=(
                    "Investigate database connection retention, "
                    "pool sizing, and connection acquisition delays "
                    "before considering operator-approved remediation."
                ),
            )

    return InvestigationReport(
        incident_id=incident_id,
        root_cause_code="INSUFFICIENT_EVIDENCE",
        diagnosis=(
            "The available diagnostic observations do not "
            "establish a sufficiently supported root cause."
        ),
        confidence="insufficient",
        evidence_ids=[item.evidence_id for item in checkpoint.evidence[:3]],
        recommendation=(
            "Collect additional service dependency, connection "
            "capacity, and timeout evidence before remediation."
        ),
    )


def format_report_summary(report: InvestigationReport) -> str:
    """Render the persisted run summary; evaluation reproduces it exactly."""
    return (
        f"Diagnosis: {report.diagnosis} "
        f"Confidence: {report.confidence}. "
        f"Evidence: {', '.join(report.evidence_ids)}. "
        f"Recommendation: {report.recommendation}"
    )
