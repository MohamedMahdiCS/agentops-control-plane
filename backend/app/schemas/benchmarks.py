"""Operator-only schemas for benchmark execution, replay and comparison."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend.app.benchmark.manifest import (
    BenchmarkManifest,
    BenchmarkStatus,
    GateStatus,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BenchmarkCreate(StrictModel):
    agent_id: UUID
    scenario_keys: list[str] | None = Field(default=None, min_length=1, max_length=20)
    label: str | None = Field(default=None, min_length=1, max_length=80)


class BenchmarkReplay(StrictModel):
    label: str | None = Field(default=None, min_length=1, max_length=80)


class PerformanceSummary(StrictModel):
    scenarios_measured: int
    total_active_ms: int
    total_tool_requests: int
    total_tool_failures: int
    max_tool_latency_ms: int | None


class BenchmarkDetail(StrictModel):
    manifest: BenchmarkManifest
    performance: PerformanceSummary


class BenchmarkSummary(StrictModel):
    benchmark_run_id: UUID
    label: str
    status: BenchmarkStatus
    gate: GateStatus
    replay_of: UUID | None
    scenario_count: int
    passed: int
    failed: int
    inconclusive: int
    incomplete: int
    git_commit_sha: str | None
    created_at: datetime


class BenchmarkListResponse(StrictModel):
    benchmarks: list[BenchmarkSummary]
    corrupt_manifests: list[str]


class ScenarioComparison(StrictModel):
    scenario_key: str
    title: str
    comparable: bool
    baseline_verdict: str | None
    candidate_verdict: str | None
    baseline_score: int | None
    candidate_score: int | None
    score_delta: int | None
    behavior_reproduced: bool
    regression: bool
    new_safety_violation: bool
    baseline_active_ms: int | None
    candidate_active_ms: int | None
    notes: list[str]


class BenchmarkComparison(StrictModel):
    baseline_id: UUID
    candidate_id: UUID
    regression: bool
    regressed_scenarios: list[str]
    fully_reproduced: bool
    baseline_gate: GateStatus
    candidate_gate: GateStatus
    scenarios: list[ScenarioComparison]
