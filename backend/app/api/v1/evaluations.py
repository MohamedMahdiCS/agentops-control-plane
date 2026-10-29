"""Operator-authenticated evaluation endpoints.

Every route requires a verified operator before any database access.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.dependencies import get_db_session
from backend.app.core.operator_auth import OperatorPrincipal, require_operator
from backend.app.evaluation.comparison import IncomparableEvaluationsError
from backend.app.models.evaluation_case import EvaluationCase
from backend.app.models.evaluation_result import EvaluationResult
from backend.app.schemas.evaluations import (
    CatalogSyncResponse,
    CriterionView,
    EvaluationCaseListResponse,
    EvaluationCaseView,
    EvaluationComparisonResponse,
    EvaluationCreate,
    EvaluationDetail,
    EvaluationListResponse,
    EvaluationMetricsView,
    EvaluationOverviewResponse,
    EvaluationSummaryView,
    SafetyGateView,
    ScenarioStatsView,
    Verdict,
)
from backend.app.services import evaluations as service

router = APIRouter(prefix="/evaluations", tags=["Evaluations"])

Operator = Annotated[OperatorPrincipal, Depends(require_operator)]
Session = Annotated[AsyncSession, Depends(get_db_session)]


def case_view(case: EvaluationCase) -> EvaluationCaseView:
    config: dict[str, Any] = case.scenario_config
    grader: dict[str, Any] = case.grader_config
    return EvaluationCaseView(
        id=case.id,
        scenario_key=case.scenario_key,
        version=case.version,
        category=case.category,
        title=str(config.get("title", case.scenario_key)),
        description=str(config.get("description", "")),
        incident_id=str(config.get("incident_id", "")),
        agent_quality=bool(config.get("agent_quality")),
        platform_assertions=bool(config.get("platform_assertions")),
        fault_count=len(config.get("faults") or []),
        has_injection=config.get("injection") is not None,
        allowed_terminal_statuses=list(case.allowed_terminal_statuses),
        passing_threshold=int(grader.get("passing_threshold", 80)),
        grader_version=int(grader.get("grader_version", 1)),
        expected_outcome=case.expected_outcome,
        created_at=case.created_at,
    )


def summary_view(
    result: EvaluationResult, case: EvaluationCase
) -> EvaluationSummaryView:
    criteria: dict[str, Any] = result.criteria_results or {}
    return EvaluationSummaryView.model_validate(
        {
            "id": result.id,
            "run_id": result.run_id,
            "scenario_key": case.scenario_key,
            "scenario_title": str(case.scenario_config.get("title", case.scenario_key)),
            "category": case.category,
            "case_version": result.case_version,
            "grader_version": result.grader_version,
            "status": result.status,
            "verdict": result.verdict,
            "score": result.score,
            "passing_threshold": result.passing_threshold,
            "policy_gate_passed": result.policy_gate_passed,
            "evidence_fingerprint": criteria.get("evidence_fingerprint"),
            "created_at": result.created_at,
            "finished_at": result.finished_at,
        }
    )


def detail_view(result: EvaluationResult, case: EvaluationCase) -> EvaluationDetail:
    criteria: dict[str, Any] = result.criteria_results or {}
    return EvaluationDetail(
        **summary_view(result, case).model_dump(),
        verdict_reason=str(criteria.get("verdict_reason", "")),
        evidence_complete=bool(criteria.get("evidence_complete", False)),
        run_snapshot=criteria.get("run_snapshot", {}),
        metrics=EvaluationMetricsView.model_validate(criteria.get("metrics", {})),
        safety_gate=SafetyGateView.model_validate(
            criteria.get("safety_gate", {"passed": None, "violations": []})
        ),
        criteria=[
            CriterionView.model_validate(item) for item in criteria.get("criteria", [])
        ],
        evidence_span_ids=list(result.evidence_span_ids),
    )


@router.get("/cases", response_model=EvaluationCaseListResponse)
async def get_cases(
    principal: Operator, session: Session
) -> EvaluationCaseListResponse:
    return EvaluationCaseListResponse(
        cases=[case_view(case) for case in await service.list_cases(session)]
    )


@router.post("/cases/sync", response_model=CatalogSyncResponse)
async def sync_cases(principal: Operator, session: Session) -> CatalogSyncResponse:
    """Publish missing scenario versions; refuse silently changed versions."""
    try:
        result = await service.sync_catalog(session)
    except service.CatalogIntegrityError as exc:
        raise HTTPException(409, "Stored scenario version was modified") from exc
    return CatalogSyncResponse(created=result.created, verified=result.verified)


@router.get("/overview", response_model=EvaluationOverviewResponse)
async def get_overview(
    principal: Operator, session: Session
) -> EvaluationOverviewResponse:
    overview = await service.evaluation_overview(session)
    return EvaluationOverviewResponse(
        total=overview.total,
        passed=overview.passed,
        failed=overview.failed,
        inconclusive=overview.inconclusive,
        gate_failures=overview.gate_failures,
        # Inconclusive results are disclosed separately, never counted as passes.
        pass_rate=round(overview.passed / overview.total, 4)
        if overview.total
        else None,
        average_score=overview.average_score,
        scenarios=[
            ScenarioStatsView(
                scenario_key=item.case.scenario_key,
                version=item.case.version,
                title=str(item.case.scenario_config.get("title", "")),
                category=item.case.category,
                total=item.total,
                passed=item.passed,
                failed=item.failed,
                inconclusive=item.inconclusive,
                average_score=item.average_score,
                latest=summary_view(item.latest, item.case) if item.latest else None,
            )
            for item in overview.scenarios
        ],
    )


@router.get("/compare", response_model=EvaluationComparisonResponse)
async def compare(
    principal: Operator,
    session: Session,
    baseline_id: Annotated[UUID, Query()],
    candidate_id: Annotated[UUID, Query()],
) -> EvaluationComparisonResponse:
    try:
        comparison = await service.compare_stored_evaluations(
            session, baseline_id, candidate_id
        )
    except service.EvaluationNotFoundError as exc:
        raise HTTPException(404, "Evaluation not found") from exc
    except IncomparableEvaluationsError as exc:
        raise HTTPException(422, f"Evaluations are not comparable: {exc}") from exc
    return EvaluationComparisonResponse.model_validate(comparison)


@router.post(
    "",
    response_model=EvaluationDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_evaluation(
    payload: EvaluationCreate,
    response: Response,
    principal: Operator,
    session: Session,
    idempotency_key: Annotated[
        str | None,
        Header(min_length=8, max_length=128),
    ] = None,
) -> EvaluationDetail:
    try:
        recorded = await service.evaluate_run(
            session,
            run_id=payload.run_id,
            scenario_key=payload.scenario_key,
            scenario_version=payload.scenario_version,
            operator_id=principal.operator_id,
            idempotency_key=idempotency_key,
        )
    except service.ScenarioNotFoundError as exc:
        raise HTTPException(404, "Evaluation scenario not found") from exc
    except service.RunNotFoundError as exc:
        raise HTTPException(404, "Agent run not found") from exc
    except service.ScenarioNotApplicableError as exc:
        raise HTTPException(409, "Scenario does not apply to this run") from exc
    except service.RunNotTerminalError as exc:
        raise HTTPException(
            409, "Run has not reached a terminal state and cannot be evaluated"
        ) from exc
    except service.EvaluationIdempotencyConflictError as exc:
        raise HTTPException(
            409, "Idempotency key already used for a different evaluation"
        ) from exc
    except service.CatalogIntegrityError as exc:
        raise HTTPException(409, "Stored scenario version was modified") from exc

    if not recorded.created:
        response.status_code = status.HTTP_200_OK
    response.headers["Location"] = f"/api/v1/evaluations/{recorded.result.id}"
    return detail_view(recorded.result, recorded.case)


@router.get("", response_model=EvaluationListResponse)
async def get_evaluations(
    principal: Operator,
    session: Session,
    run_id: Annotated[UUID | None, Query()] = None,
    scenario_key: Annotated[str | None, Query(pattern=r"^[A-Z][0-9]{2}$")] = None,
    verdict: Annotated[Verdict | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> EvaluationListResponse:
    rows = await service.list_evaluations(
        session,
        run_id=run_id,
        scenario_key=scenario_key,
        verdict=verdict,
        limit=limit,
    )
    return EvaluationListResponse(
        evaluations=[summary_view(result, case) for result, case in rows]
    )


@router.get("/{evaluation_id}", response_model=EvaluationDetail)
async def get_evaluation(
    evaluation_id: UUID, principal: Operator, session: Session
) -> EvaluationDetail:
    try:
        result, case = await service.get_evaluation(session, evaluation_id)
    except service.EvaluationNotFoundError as exc:
        raise HTTPException(404, "Evaluation not found") from exc
    return detail_view(result, case)
