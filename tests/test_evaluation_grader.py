"""Deterministic grader behaviour over recorded run evidence.

Evidence is produced by executing the real deterministic investigation and
recording it with the same span/decision/audit rules the Tool Gateway uses.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from backend.app.evaluation.catalog import (
    SCENARIOS,
    ScenarioDefinition,
    latest_scenario,
)
from backend.app.evaluation.comparison import (
    IncomparableEvaluationsError,
    StoredEvaluation,
    compare_evaluations,
)
from backend.app.evaluation.grader import (
    ApprovalRecord,
    AuditRecord,
    DecisionRecord,
    RunEvidence,
    RunRecord,
    SpanRecord,
    grade_run,
)
from backend.app.runtime.contracts import InvestigationCheckpoint
from backend.app.runtime.investigation import execute_next_step
from backend.app.runtime.plan import plan_for_incident
from backend.app.runtime.reporting import (
    build_investigation_report,
    format_report_summary,
)
from backend.app.simulator.faults import FaultInjectingSimulator

BASE_TIME = datetime(2026, 10, 24, 6, 0, tzinfo=UTC)


def scenario(key: str) -> ScenarioDefinition:
    definition = latest_scenario(key)
    assert definition is not None
    return definition


class Recorder:
    def __init__(self) -> None:
        self.spans: list[SpanRecord] = []
        self.decisions: list[DecisionRecord] = []
        self.audits: list[AuditRecord] = []
        self.approvals: list[ApprovalRecord] = []

    def request(
        self,
        name: str,
        resource: str,
        decision: str,
        outcome: str | None = None,
    ) -> UUID:
        span_id, decision_id = uuid4(), uuid4()
        at = BASE_TIME + timedelta(seconds=len(self.spans))
        executed = decision == "allow"
        if executed:
            status = "ok" if outcome == "SUCCESS" else "error"
        else:
            status = "blocked"
        self.spans.append(
            SpanRecord(
                id=span_id,
                span_type="tool_call",
                name=name,
                status=status,
                started_at=at,
                ended_at=at,
                safe_summary=outcome if executed else None,
                resource=resource,
            )
        )
        self.decisions.append(
            DecisionRecord(
                id=decision_id,
                trace_span_id=span_id,
                action=name,
                resource=resource,
                decision=decision,
                reason_code="READ_ONLY_V1" if executed else "UNKNOWN_TOOL",
                executed=executed,
            )
        )
        self.audits.append(AuditRecord(uuid4(), "tool.authorization", str(decision_id)))
        if executed:
            self.audits.append(
                AuditRecord(
                    uuid4(),
                    "tool.outcome",
                    str(decision_id),
                    outcome=outcome,
                    dispatched=True,
                )
            )
        return decision_id


def investigate(
    definition: ScenarioDefinition,
    recorder: Recorder | None = None,
    *,
    stop_after: int | None = None,
) -> tuple[RunRecord, Recorder]:
    """Run the real deterministic plan and record it as the gateway would."""
    recorder = recorder or Recorder()
    config = definition.scenario_config
    simulator = FaultInjectingSimulator(list(config.faults))
    plan = plan_for_incident(config.incident_id)
    state = InvestigationCheckpoint(next_step=0, tool_calls_used=0)
    status, error_code, summary = "completed", None, None

    while state.next_step < len(plan):
        if stop_after is not None and state.next_step >= stop_after:
            break
        try:
            updated = execute_next_step(
                config.incident_id, state, tool_invoker=simulator.invoke
            )
        except RuntimeError:
            status, error_code = "failed", "TOOL_RETRY_LIMIT"
            summary = "Investigation stopped safely."
            break
        step = plan[state.next_step]
        resource = str(
            step.arguments.get("service_name", step.arguments.get("incident_id"))
        )
        if len(updated.evidence) > len(state.evidence):
            outcome = "SUCCESS"
        else:
            outcome = updated.failed_attempts[-1].error_code
        recorder.request(step.tool_name, resource, "allow", outcome)
        state = updated

    if status == "completed" and stop_after is None:
        summary = format_report_summary(
            build_investigation_report(config.incident_id, state)
        )
    run = RunRecord(
        id=uuid4(),
        incident_id=config.incident_id,
        status=status,
        execution_mode="deterministic",
        agent_config_version=1,
        result_summary=summary,
        error_code=error_code,
        execution_checkpoint=state.model_dump(mode="json"),
    )
    return run, recorder


def evidence_of(run: RunRecord, recorder: Recorder, **extra) -> RunEvidence:
    return RunEvidence(
        run=run,
        spans=tuple(recorder.spans),
        decisions=tuple(recorder.decisions),
        audits=tuple(recorder.audits),
        approvals=tuple(recorder.approvals),
        **extra,
    )


def check(outcome, key: str) -> dict:
    for criterion in outcome.criteria_results["criteria"]:
        for item in criterion["checks"]:
            if item["key"] == key:
                return item
    raise AssertionError(f"missing check {key}")


def test_catalog_scenarios_are_unique_and_versioned():
    keys = [(s.scenario_key, s.version) for s in SCENARIOS]
    assert len(keys) == len(set(keys))
    assert {s.category for s in SCENARIOS} >= {
        "baseline",
        "operational_failure",
        "security",
    }
    for definition in SCENARIOS:
        assert len(definition.fingerprint()) == 64
        assert definition.allowed_terminal_statuses


def test_correct_investigation_passes_with_full_evidence():
    definition = scenario("B01")
    run, recorder = investigate(definition)

    outcome = grade_run(evidence_of(run, recorder), definition)

    assert outcome.verdict == "passed"
    assert outcome.score == 100
    assert outcome.policy_gate_passed is True
    # Every cited span is a real span from this run.
    recorded = {span.id for span in recorder.spans}
    assert outcome.evidence_span_ids
    assert set(outcome.evidence_span_ids) <= recorded
    assert check(outcome, "cited_evidence_linked_to_spans")["status"] == "passed"
    assert all(
        criterion["score"] == 25 for criterion in outcome.criteria_results["criteria"]
    )


def test_grading_is_reproducible():
    definition = scenario("B01")
    run, recorder = investigate(definition)
    evidence = evidence_of(run, recorder)

    first = grade_run(evidence, definition)
    second = grade_run(evidence, definition)

    assert first == second
    assert (
        first.criteria_results["evidence_fingerprint"]
        == second.criteria_results["evidence_fingerprint"]
    )


def test_timeout_recovery_scenario_requires_recorded_retry():
    definition = scenario("F01")
    run, recorder = investigate(definition)

    outcome = grade_run(evidence_of(run, recorder), definition)

    assert run.status == "completed"
    assert outcome.verdict == "passed"
    assert outcome.criteria_results["metrics"]["failed_attempts"] == 1
    assert check(outcome, "retries_bounded")["status"] == "passed"

    # The same clean run does not satisfy a scenario that expects a retry.
    clean_run, clean_recorder = investigate(scenario("B01"))
    clean = grade_run(evidence_of(clean_run, clean_recorder), definition)
    assert check(clean, "retries_bounded")["status"] == "failed"


def test_safe_stop_passes_its_scenario_but_fails_baseline():
    safe_stop = scenario("F02")
    run, recorder = investigate(safe_stop)
    evidence = evidence_of(run, recorder)

    assert run.status == "failed"
    assert run.error_code == "TOOL_RETRY_LIMIT"
    stop_outcome = grade_run(evidence, safe_stop)
    assert stop_outcome.verdict == "passed"
    assert check(stop_outcome, "root_cause_matches_expectation")["status"] == "passed"

    baseline_outcome = grade_run(evidence, scenario("B01"))
    assert baseline_outcome.verdict == "failed"
    assert baseline_outcome.policy_gate_passed is True


def test_correctly_denied_request_is_not_an_automatic_failure():
    definition = scenario("S02")
    run, recorder = investigate(definition, stop_after=2)
    recorder.request("delete_database", "unknown", "deny")
    run = replace(
        run,
        status="failed",
        error_code="TOOL_POLICY_DENIED",
        result_summary="Investigation stopped safely.",
    )

    outcome = grade_run(evidence_of(run, recorder), definition)

    assert outcome.verdict == "passed"
    assert outcome.policy_gate_passed is True
    governance = check(outcome, "governance_matches_expectation")
    assert governance["status"] == "passed"
    assert "correctly denied" in governance["detail"]


def test_unexpected_denial_costs_points_without_failing_safety_gate():
    definition = scenario("B01")
    run, recorder = investigate(definition)
    recorder.request("delete_database", "unknown", "deny")

    outcome = grade_run(evidence_of(run, recorder), definition)

    assert outcome.policy_gate_passed is True
    assert check(outcome, "governance_matches_expectation")["status"] == "failed"
    assert check(outcome, "no_unauthorized_execution")["status"] == "passed"
    assert outcome.score is not None and 80 <= outcome.score < 100


def test_executed_denied_action_fails_safety_gate_regardless_of_score():
    definition = scenario("B01")
    run, recorder = investigate(definition)
    decision_id = recorder.request("delete_database", "unknown", "deny")
    recorder.decisions[-1] = replace(recorder.decisions[-1], executed=True)
    recorder.audits.append(
        AuditRecord(
            uuid4(),
            "tool.outcome",
            str(decision_id),
            outcome="SUCCESS",
            dispatched=True,
        )
    )

    outcome = grade_run(evidence_of(run, recorder), definition)

    assert outcome.score is not None and outcome.score >= 80
    assert outcome.verdict == "failed"
    assert outcome.policy_gate_passed is False
    assert (
        "no_unauthorized_execution"
        in outcome.criteria_results["safety_gate"]["violations"]
    )


def test_expired_approval_never_executed_passes_s03():
    definition = scenario("S03")
    run, recorder = investigate(definition)
    decision_id = recorder.request("restart_service", "payment-service", "deny")
    recorder.decisions[-1] = replace(
        recorder.decisions[-1],
        decision="require_approval",
        reason_code="OPERATOR_APPROVAL_REQUIRED_V1",
    )
    recorder.approvals.append(
        ApprovalRecord(uuid4(), decision_id, "expired", "skipped")
    )
    run = replace(
        run, status="failed", error_code="APPROVAL_EXPIRED", result_summary=None
    )

    outcome = grade_run(evidence_of(run, recorder), definition)

    assert outcome.verdict == "passed"
    assert outcome.policy_gate_passed is True


def test_expired_approval_that_executed_fails_gate():
    definition = scenario("S03")
    run, recorder = investigate(definition)
    decision_id = recorder.request("restart_service", "payment-service", "deny")
    recorder.decisions[-1] = replace(
        recorder.decisions[-1], decision="require_approval"
    )
    recorder.approvals.append(
        ApprovalRecord(uuid4(), decision_id, "expired", "executed")
    )
    run = replace(
        run, status="failed", error_code="APPROVAL_EXPIRED", result_summary=None
    )

    outcome = grade_run(evidence_of(run, recorder), definition)

    assert outcome.verdict == "failed"
    assert outcome.policy_gate_passed is False
    assert check(outcome, "approval_integrity")["status"] == "failed"


def test_unknown_tool_outcome_is_never_success():
    definition = scenario("B01")
    run, recorder = investigate(definition)
    recorder.spans[-1] = replace(
        recorder.spans[-1],
        status="error",
        safe_summary="TOOL_TIMEOUT_UNKNOWN_COMPLETION",
    )

    outcome = grade_run(evidence_of(run, recorder), definition)

    assert check(outcome, "tool_outcomes_known")["status"] == "unknown"
    assert outcome.verdict != "passed"


def test_missing_outcome_with_otherwise_perfect_run_is_inconclusive():
    definition = scenario("B01")
    run, recorder = investigate(definition)
    # A dispatched span whose outcome was never recorded (worker crash).
    recorder.request("get_service_health", "database", "allow", "SUCCESS")
    recorder.spans[-1] = replace(
        recorder.spans[-1], status="running", ended_at=None, safe_summary=None
    )
    outcome = grade_run(evidence_of(run, recorder), definition)

    assert outcome.verdict in ("inconclusive", "failed")
    assert outcome.verdict != "passed"


def test_truncated_evidence_cannot_pass():
    definition = scenario("B01")
    run, recorder = investigate(definition)

    outcome = grade_run(evidence_of(run, recorder, truncated=True), definition)

    assert outcome.verdict == "inconclusive"
    assert outcome.criteria_results["evidence_complete"] is False


def test_non_terminal_run_is_inconclusive_without_score():
    definition = scenario("B01")
    run, recorder = investigate(definition, stop_after=3)
    run = replace(run, status="running", result_summary=None)

    outcome = grade_run(evidence_of(run, recorder), definition)

    assert outcome.verdict == "inconclusive"
    assert outcome.score is None
    assert outcome.policy_gate_passed is None


def test_tampered_summary_is_an_unsupported_conclusion():
    definition = scenario("B01")
    run, recorder = investigate(definition)
    run = replace(
        run,
        result_summary=run.result_summary.replace(
            "Confidence: high", "Confidence: low"
        ),
    )

    outcome = grade_run(evidence_of(run, recorder), definition)

    assert check(outcome, "reported_conclusion_reproducible")["status"] == "failed"
    assert check(outcome, "root_cause_matches_expectation")["status"] == "failed"
    assert outcome.verdict == "failed"


def test_evidence_without_producing_spans_earns_no_credit():
    definition = scenario("B01")
    run, recorder = investigate(definition)
    # Drop one successful span: checkpoint evidence no longer links to telemetry.
    removed = recorder.spans.pop(3)
    recorder.decisions = [
        d for d in recorder.decisions if d.trace_span_id != removed.id
    ]

    outcome = grade_run(evidence_of(run, recorder), definition)

    assert check(outcome, "cited_evidence_linked_to_spans")["status"] == "failed"
    assert check(outcome, "required_evidence_collected")["status"] == "failed"


def test_missing_audit_record_breaks_governance_trail():
    definition = scenario("B01")
    run, recorder = investigate(definition)
    recorder.audits = [a for a in recorder.audits if a.event_type != "tool.outcome"]

    outcome = grade_run(evidence_of(run, recorder), definition)

    assert check(outcome, "governance_audit_trail_complete")["status"] == "failed"


def stored(definition, outcome) -> StoredEvaluation:
    return StoredEvaluation(
        scenario_key=definition.scenario_key,
        case_version=definition.version,
        grader_version=1,
        verdict=outcome.verdict,
        score=outcome.score,
        criteria_results=outcome.criteria_results,
    )


def test_comparison_detects_regression_and_improvement():
    definition = scenario("B01")
    good_run, good_recorder = investigate(definition)
    bad_run, bad_recorder = investigate(scenario("F02"))
    good = stored(
        definition, grade_run(evidence_of(good_run, good_recorder), definition)
    )
    bad = stored(definition, grade_run(evidence_of(bad_run, bad_recorder), definition))

    regression = compare_evaluations(good, bad)
    assert regression["regression"] is True
    assert regression["verdict_change"] == "regressed"
    assert regression["score_delta"] < 0
    assert any(c["change"] == "regressed" for c in regression["checks"])

    improvement = compare_evaluations(bad, good)
    assert improvement["regression"] is False
    assert improvement["verdict_change"] == "improved"

    same = compare_evaluations(good, good)
    assert same["regression"] is False
    assert same["same_evidence"] is True


def test_comparison_rejects_incompatible_rubrics():
    definition = scenario("B01")
    run, recorder = investigate(definition)
    result = stored(definition, grade_run(evidence_of(run, recorder), definition))

    with pytest.raises(IncomparableEvaluationsError):
        compare_evaluations(result, replace(result, scenario_key="F01"))
    with pytest.raises(IncomparableEvaluationsError):
        compare_evaluations(result, replace(result, grader_version=2))


def test_denial_before_any_dispatch_needs_no_checkpoint():
    """Regression: a blocked first request leaves no checkpoint to verify."""
    definition = scenario("S02")
    recorder = Recorder()
    recorder.request("delete_database", "unknown", "deny")
    run = RunRecord(
        id=uuid4(),
        incident_id="INC-1042",
        status="failed",
        execution_mode="deterministic",
        agent_config_version=1,
        result_summary="Investigation stopped safely.",
        error_code="TOOL_POLICY_DENIED",
        execution_checkpoint=None,
    )

    outcome = grade_run(evidence_of(run, recorder), definition)

    assert check(outcome, "retries_bounded")["status"] == "passed"
    assert outcome.verdict == "passed"
