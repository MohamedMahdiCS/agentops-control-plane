"""Evaluation persistence: catalog sync, evidence loading, grading and history.

PostgreSQL is authoritative for run evidence. Evidence is read inside one
REPEATABLE READ transaction so a grade reflects a single consistent snapshot.
"""

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.evaluation.catalog import (
    GRADER_VERSION,
    SCENARIOS,
    ScenarioDefinition,
    content_fingerprint,
    latest_scenario,
    scenario_index,
)
from backend.app.evaluation.comparison import StoredEvaluation, compare_evaluations
from backend.app.evaluation.grader import (
    TERMINAL_STATUSES,
    ApprovalRecord,
    AuditRecord,
    DecisionRecord,
    RunEvidence,
    RunRecord,
    SpanRecord,
    grade_run,
)
from backend.app.models.agent_run import AgentRun
from backend.app.models.approval_request import ApprovalRequest
from backend.app.models.audit_event import AuditEvent
from backend.app.models.evaluation_case import EvaluationCase
from backend.app.models.evaluation_result import EvaluationResult
from backend.app.models.policy_decision import PolicyDecision
from backend.app.models.trace_span import TraceSpan

SPAN_LIMIT = 200
DECISION_LIMIT = 200
AUDIT_LIMIT = 500
APPROVAL_LIMIT = 50


class CatalogIntegrityError(RuntimeError):
    """A stored scenario version differs from the published definition."""


class ScenarioNotFoundError(LookupError):
    pass


class RunNotFoundError(LookupError):
    pass


class ScenarioNotApplicableError(ValueError):
    pass


class RunNotTerminalError(ValueError):
    """Only terminal runs can receive a final evaluation."""


class EvaluationIdempotencyConflictError(Exception):
    pass


class EvaluationNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class CatalogSyncResult:
    created: int
    verified: int


@dataclass(frozen=True)
class RecordedEvaluation:
    result: EvaluationResult
    case: EvaluationCase
    created: bool


def _stored_fields(case: EvaluationCase) -> dict[str, object]:
    return {
        "scenario_key": case.scenario_key,
        "version": case.version,
        "category": case.category,
        "scenario_config": case.scenario_config,
        "expected_outcome": case.expected_outcome,
        "grader_config": case.grader_config,
        "allowed_terminal_statuses": list(case.allowed_terminal_statuses),
    }


async def _ensure_case(
    session: AsyncSession, definition: ScenarioDefinition
) -> tuple[EvaluationCase, bool]:
    fields = definition.stored_fields()
    inserted = await session.scalar(
        insert(EvaluationCase)
        .values(id=uuid4(), **fields)
        .on_conflict_do_nothing(constraint="uq_evaluation_cases_scenario_key_version")
        .returning(EvaluationCase.id)
    )
    case = await session.scalar(
        select(EvaluationCase)
        .where(
            EvaluationCase.scenario_key == definition.scenario_key,
            EvaluationCase.version == definition.version,
        )
        .execution_options(populate_existing=True)
    )
    if case is None:
        raise RuntimeError("Evaluation case could not be retrieved")
    if content_fingerprint(_stored_fields(case)) != definition.fingerprint():
        raise CatalogIntegrityError(
            f"Stored scenario {definition.scenario_key} v{definition.version} "
            "differs from the published definition"
        )
    return case, inserted is not None


async def sync_catalog(
    session: AsyncSession,
    scenarios: tuple[ScenarioDefinition, ...] = SCENARIOS,
) -> CatalogSyncResult:
    """Insert missing scenario versions and verify existing ones are unchanged."""
    created = verified = 0
    async with session.begin():
        for definition in scenarios:
            _, was_created = await _ensure_case(session, definition)
            if was_created:
                created += 1
            else:
                verified += 1
    return CatalogSyncResult(created=created, verified=verified)


async def list_cases(session: AsyncSession) -> list[EvaluationCase]:
    return list(
        (
            await session.scalars(
                select(EvaluationCase).order_by(
                    EvaluationCase.scenario_key, EvaluationCase.version
                )
            )
        ).all()
    )


async def load_run_evidence(session: AsyncSession, run_id: UUID) -> RunEvidence | None:
    """Load bounded run evidence. Truncation is recorded, never hidden."""
    run = await session.get(AgentRun, run_id, populate_existing=True)
    if run is None:
        return None

    spans = (
        await session.scalars(
            select(TraceSpan)
            .where(TraceSpan.run_id == run_id)
            .order_by(TraceSpan.started_at, TraceSpan.id)
            .limit(SPAN_LIMIT + 1)
        )
    ).all()
    decisions = (
        await session.scalars(
            select(PolicyDecision)
            .where(PolicyDecision.run_id == run_id)
            .order_by(PolicyDecision.created_at, PolicyDecision.id)
            .limit(DECISION_LIMIT + 1)
        )
    ).all()
    # Evaluation audit records are excluded so regrading reads identical input.
    audits = (
        await session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.run_id == run_id,
                AuditEvent.event_type.not_like("evaluation.%"),
            )
            .order_by(AuditEvent.created_at, AuditEvent.id)
            .limit(AUDIT_LIMIT + 1)
        )
    ).all()
    approvals = (
        await session.scalars(
            select(ApprovalRequest)
            .where(ApprovalRequest.run_id == run_id)
            .order_by(ApprovalRequest.requested_at, ApprovalRequest.id)
            .limit(APPROVAL_LIMIT + 1)
        )
    ).all()

    truncated = (
        len(spans) > SPAN_LIMIT
        or len(decisions) > DECISION_LIMIT
        or len(audits) > AUDIT_LIMIT
        or len(approvals) > APPROVAL_LIMIT
    )

    def payload_value(event: AuditEvent, key: str) -> object:
        payload = event.event_payload if isinstance(event.event_payload, dict) else {}
        return payload.get(key)

    return RunEvidence(
        run=RunRecord(
            id=run.id,
            incident_id=run.incident_id,
            status=run.status,
            execution_mode=run.execution_mode,
            agent_config_version=run.agent_config_version,
            result_summary=run.result_summary,
            error_code=run.error_code,
            execution_checkpoint=run.execution_checkpoint,
        ),
        spans=tuple(
            SpanRecord(
                id=span.id,
                span_type=span.span_type,
                name=span.name,
                status=span.status,
                started_at=span.started_at,
                ended_at=span.ended_at,
                safe_summary=span.safe_summary,
                resource=resource
                if isinstance(
                    resource := (span.sanitized_attributes or {}).get("resource"), str
                )
                else None,
            )
            for span in spans[:SPAN_LIMIT]
        ),
        decisions=tuple(
            DecisionRecord(
                id=decision.id,
                trace_span_id=decision.trace_span_id,
                action=decision.action,
                resource=decision.resource,
                decision=decision.decision,
                reason_code=decision.reason_code,
                executed=decision.executed,
            )
            for decision in decisions[:DECISION_LIMIT]
        ),
        audits=tuple(
            AuditRecord(
                id=event.id,
                event_type=event.event_type,
                resource_id=event.resource_id,
                outcome=outcome
                if isinstance(outcome := payload_value(event, "outcome"), str)
                else None,
                dispatched=dispatched
                if isinstance(dispatched := payload_value(event, "dispatched"), bool)
                else None,
            )
            for event in audits[:AUDIT_LIMIT]
        ),
        approvals=tuple(
            ApprovalRecord(
                id=approval.id,
                policy_decision_id=approval.policy_decision_id,
                status=approval.status,
                execution_status=approval.execution_status,
            )
            for approval in approvals[:APPROVAL_LIMIT]
        ),
        truncated=truncated,
    )


def evaluation_request_fingerprint(
    run_id: UUID, scenario_key: str, version: int
) -> str:
    request = {
        "grader_version": GRADER_VERSION,
        "run_id": str(run_id),
        "scenario_key": scenario_key,
        "scenario_version": version,
    }
    canonical = json.dumps(request, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def resolve_scenario(scenario_key: str, version: int | None) -> ScenarioDefinition:
    definition = (
        latest_scenario(scenario_key)
        if version is None
        else scenario_index().get((scenario_key, version))
    )
    if definition is None:
        raise ScenarioNotFoundError(scenario_key)
    return definition


async def evaluate_run(
    session: AsyncSession,
    *,
    run_id: UUID,
    scenario_key: str,
    scenario_version: int | None,
    operator_id: str,
    idempotency_key: str | None = None,
) -> RecordedEvaluation:
    """Grade a run against a published scenario and append the result."""
    definition = resolve_scenario(scenario_key, scenario_version)
    fingerprint = evaluation_request_fingerprint(
        run_id, definition.scenario_key, definition.version
    )

    async with session.begin():
        case, _ = await _ensure_case(session, definition)

    async with session.begin():
        # The snapshot must be established before the first evidence read.
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))

        if idempotency_key is not None:
            existing = await session.scalar(
                select(EvaluationResult).where(
                    EvaluationResult.idempotency_key == idempotency_key
                )
            )
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise EvaluationIdempotencyConflictError()
                return RecordedEvaluation(existing, case, created=False)

        evidence = await load_run_evidence(session, run_id)
        if evidence is None:
            raise RunNotFoundError(run_id)

        config = definition.scenario_config
        if (
            evidence.run.incident_id != config.incident_id
            or evidence.run.execution_mode != config.execution_mode
        ):
            raise ScenarioNotApplicableError(
                f"Scenario {definition.scenario_key} targets {config.incident_id} "
                f"in {config.execution_mode} mode"
            )

        if evidence.run.status not in TERMINAL_STATUSES:
            raise RunNotTerminalError(evidence.run.status)

        outcome = grade_run(evidence, definition)
        result_id = uuid4()
        inserted = await session.scalar(
            insert(EvaluationResult)
            .values(
                id=result_id,
                run_id=run_id,
                evaluation_case_id=case.id,
                case_version=definition.version,
                grader_version=GRADER_VERSION,
                status="completed",
                verdict=outcome.verdict,
                score=outcome.score,
                passing_threshold=outcome.passing_threshold,
                policy_gate_passed=outcome.policy_gate_passed,
                criteria_results=outcome.criteria_results,
                evidence_span_ids=outcome.evidence_span_ids,
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                attempt_count=1,
                finished_at=func.clock_timestamp(),
            )
            .on_conflict_do_nothing(
                constraint="uq_evaluation_results_run_case_idempotency"
            )
            .returning(EvaluationResult.id)
        )

        if inserted is None:
            existing = await session.scalar(
                select(EvaluationResult).where(
                    EvaluationResult.run_id == run_id,
                    EvaluationResult.evaluation_case_id == case.id,
                    EvaluationResult.idempotency_key == idempotency_key,
                )
            )
            if existing is None or existing.request_fingerprint != fingerprint:
                raise EvaluationIdempotencyConflictError()
            return RecordedEvaluation(existing, case, created=False)

        session.add(
            AuditEvent(
                run_id=run_id,
                actor_type="operator",
                actor_identifier=operator_id,
                event_type="evaluation.recorded",
                resource_type="evaluation_result",
                resource_id=str(result_id),
                event_payload={
                    "scenario_key": definition.scenario_key,
                    "case_version": definition.version,
                    "grader_version": GRADER_VERSION,
                    "verdict": outcome.verdict,
                    "score": outcome.score,
                    "policy_gate_passed": outcome.policy_gate_passed,
                    "evidence_fingerprint": outcome.criteria_results[
                        "evidence_fingerprint"
                    ],
                },
            )
        )
        await session.flush()
        result = await session.get(EvaluationResult, result_id)
        if result is None:
            raise RuntimeError("Recorded evaluation could not be retrieved")

    return RecordedEvaluation(result, case, created=True)


async def list_evaluations(
    session: AsyncSession,
    *,
    run_id: UUID | None = None,
    scenario_key: str | None = None,
    verdict: str | None = None,
    limit: int = 50,
) -> list[tuple[EvaluationResult, EvaluationCase]]:
    statement = (
        select(EvaluationResult, EvaluationCase)
        .join(EvaluationCase, EvaluationCase.id == EvaluationResult.evaluation_case_id)
        .order_by(EvaluationResult.created_at.desc(), EvaluationResult.id.desc())
        .limit(limit)
    )
    if run_id is not None:
        statement = statement.where(EvaluationResult.run_id == run_id)
    if scenario_key is not None:
        statement = statement.where(EvaluationCase.scenario_key == scenario_key)
    if verdict is not None:
        statement = statement.where(EvaluationResult.verdict == verdict)
    rows = (await session.execute(statement)).all()
    return [(row[0], row[1]) for row in rows]


async def get_evaluation(
    session: AsyncSession, evaluation_id: UUID
) -> tuple[EvaluationResult, EvaluationCase]:
    row = (
        await session.execute(
            select(EvaluationResult, EvaluationCase)
            .join(
                EvaluationCase,
                EvaluationCase.id == EvaluationResult.evaluation_case_id,
            )
            .where(EvaluationResult.id == evaluation_id)
        )
    ).first()
    if row is None:
        raise EvaluationNotFoundError(evaluation_id)
    return row[0], row[1]


@dataclass(frozen=True)
class ScenarioStats:
    case: EvaluationCase
    total: int
    passed: int
    failed: int
    inconclusive: int
    average_score: float | None
    latest: EvaluationResult | None


@dataclass
class _Tally:
    passed: int = 0
    failed: int = 0
    inconclusive: int = 0
    score_sum: float = 0.0
    scored: int = 0

    def add(self, verdict: str | None, count: int, score_sum: float | None) -> None:
        if verdict == "passed":
            self.passed += count
        elif verdict == "failed":
            self.failed += count
        elif verdict == "inconclusive":
            self.inconclusive += count
        if score_sum is not None:
            self.score_sum += score_sum
            self.scored += count

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.inconclusive

    @property
    def average(self) -> float | None:
        return round(self.score_sum / self.scored, 1) if self.scored else None


@dataclass(frozen=True)
class EvaluationOverview:
    total: int
    passed: int
    failed: int
    inconclusive: int
    gate_failures: int
    average_score: float | None
    scenarios: list[ScenarioStats]


async def evaluation_overview(session: AsyncSession) -> EvaluationOverview:
    """Aggregate stored results only; nothing is estimated or synthesized."""
    rows = (
        await session.execute(
            select(
                EvaluationResult.evaluation_case_id,
                EvaluationResult.verdict,
                func.count(),
                func.avg(EvaluationResult.score),
                func.count().filter(EvaluationResult.policy_gate_passed.is_(False)),
            ).group_by(EvaluationResult.evaluation_case_id, EvaluationResult.verdict)
        )
    ).all()

    latest_rows = (
        await session.scalars(
            select(EvaluationResult)
            .ext(distinct_on(EvaluationResult.evaluation_case_id))
            .order_by(
                EvaluationResult.evaluation_case_id,
                EvaluationResult.created_at.desc(),
                EvaluationResult.id.desc(),
            )
        )
    ).all()
    latest = {row.evaluation_case_id: row for row in latest_rows}

    per_case: dict[UUID, _Tally] = {}
    overall = _Tally()
    gate_failures = 0
    for case_id, verdict, count, average, gate_failed in rows:
        tally = per_case.setdefault(case_id, _Tally())
        gate_failures += gate_failed
        # Inconclusive results are counted but excluded from score averages.
        scored = average is not None and verdict != "inconclusive"
        for target in (tally, overall):
            target.add(verdict, count, float(average) * count if scored else None)

    scenarios = [
        ScenarioStats(
            case=case,
            total=(tally := per_case.get(case.id, _Tally())).total,
            passed=tally.passed,
            failed=tally.failed,
            inconclusive=tally.inconclusive,
            average_score=tally.average,
            latest=latest.get(case.id),
        )
        for case in await list_cases(session)
    ]

    return EvaluationOverview(
        total=overall.total,
        passed=overall.passed,
        failed=overall.failed,
        inconclusive=overall.inconclusive,
        gate_failures=gate_failures,
        average_score=overall.average,
        scenarios=scenarios,
    )


async def compare_stored_evaluations(
    session: AsyncSession, baseline_id: UUID, candidate_id: UUID
) -> dict[str, object]:
    baseline, baseline_case = await get_evaluation(session, baseline_id)
    candidate, candidate_case = await get_evaluation(session, candidate_id)

    def stored(result: EvaluationResult, case: EvaluationCase) -> StoredEvaluation:
        return StoredEvaluation(
            scenario_key=case.scenario_key,
            case_version=result.case_version,
            grader_version=result.grader_version,
            verdict=result.verdict,
            score=result.score,
            criteria_results=result.criteria_results,
        )

    comparison = compare_evaluations(
        stored(baseline, baseline_case), stored(candidate, candidate_case)
    )
    comparison["baseline_id"] = baseline.id
    comparison["candidate_id"] = candidate.id
    comparison["baseline_run_id"] = baseline.run_id
    comparison["candidate_run_id"] = candidate.run_id
    return comparison
