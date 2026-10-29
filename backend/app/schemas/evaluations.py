"""Explicit, operator-only schemas for evaluation results and history."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Verdict = Literal["passed", "failed", "inconclusive"]
CheckStatus = Literal["passed", "failed", "unknown", "not_applicable"]
Change = Literal["improved", "regressed", "unchanged"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvaluationCreate(StrictModel):
    run_id: UUID
    scenario_key: str = Field(pattern=r"^[A-Z][0-9]{2}$")
    scenario_version: int | None = Field(default=None, ge=1, le=1000)


class EvaluationCaseView(StrictModel):
    id: UUID
    scenario_key: str
    version: int
    category: str
    title: str
    description: str
    incident_id: str
    agent_quality: bool
    platform_assertions: bool
    fault_count: int
    has_injection: bool
    allowed_terminal_statuses: list[str]
    passing_threshold: int
    grader_version: int
    expected_outcome: dict[str, object]
    created_at: datetime


class EvaluationCaseListResponse(StrictModel):
    cases: list[EvaluationCaseView]


class CatalogSyncResponse(StrictModel):
    created: int
    verified: int


class CheckView(StrictModel):
    key: str
    title: str
    status: CheckStatus
    points_possible: int
    points_awarded: int
    detail: str
    evidence: list[str]
    safety_gate: bool


class CriterionView(StrictModel):
    key: str
    title: str
    weight: int
    points_possible: int
    points_awarded: int
    score: int | None
    checks: list[CheckView]


class SafetyGateView(StrictModel):
    passed: bool | None
    violations: list[str]


class EvaluationMetricsView(StrictModel):
    tool_requests: int
    successful_tool_calls: int
    failed_attempts: int | None
    denied_requests: int
    approval_requests: int
    unknown_points: int


class EvaluationSummaryView(StrictModel):
    id: UUID
    run_id: UUID
    scenario_key: str
    scenario_title: str
    category: str
    case_version: int
    grader_version: int
    status: str
    verdict: Verdict | None
    score: int | None = Field(default=None, ge=0, le=100)
    passing_threshold: int
    policy_gate_passed: bool | None
    evidence_fingerprint: str | None
    created_at: datetime
    finished_at: datetime | None


class EvaluationDetail(EvaluationSummaryView):
    verdict_reason: str
    evidence_complete: bool
    run_snapshot: dict[str, object]
    metrics: EvaluationMetricsView
    safety_gate: SafetyGateView
    criteria: list[CriterionView]
    evidence_span_ids: list[UUID]


class EvaluationListResponse(StrictModel):
    evaluations: list[EvaluationSummaryView]


class ScenarioStatsView(StrictModel):
    scenario_key: str
    version: int
    title: str
    category: str
    total: int
    passed: int
    failed: int
    inconclusive: int
    average_score: float | None
    latest: EvaluationSummaryView | None


class EvaluationOverviewResponse(StrictModel):
    total: int
    passed: int
    failed: int
    inconclusive: int
    gate_failures: int
    pass_rate: float | None
    average_score: float | None
    scenarios: list[ScenarioStatsView]


class CriterionDeltaView(StrictModel):
    key: str
    title: str
    baseline_score: int | None
    candidate_score: int | None
    delta: int | None


class CheckDeltaView(StrictModel):
    criterion: str
    key: str
    title: str
    baseline_status: CheckStatus
    candidate_status: CheckStatus
    change: Change


class EvaluationComparisonResponse(StrictModel):
    baseline_id: UUID
    candidate_id: UUID
    baseline_run_id: UUID
    candidate_run_id: UUID
    scenario_key: str
    case_version: int
    grader_version: int
    baseline_verdict: Verdict | None
    candidate_verdict: Verdict | None
    verdict_change: Change
    baseline_score: int | None
    candidate_score: int | None
    score_delta: int | None
    regression: bool
    same_evidence: bool
    new_safety_violations: list[str]
    resolved_safety_violations: list[str]
    criteria: list[CriterionDeltaView]
    checks: list[CheckDeltaView]
