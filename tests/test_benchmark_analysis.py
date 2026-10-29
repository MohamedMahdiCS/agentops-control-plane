"""Manifest integrity, release gates, comparison and reporting (no database)."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from backend.app.benchmark.analysis import (
    IncomparableBenchmarksError,
    compare_benchmarks,
    compute_gates,
    markdown_report,
    percentile,
)
from backend.app.benchmark.manifest import (
    BenchmarkManifest,
    ManifestCorruptError,
    ManifestNotFoundError,
    ManifestStore,
    ScenarioOutcome,
    ScenarioPerformance,
)
from backend.app.runtime.worker import HarnessInjection

NOW = datetime(2026, 10, 29, tzinfo=UTC)


def outcome(key="B01", *, agent=True, platform=True, **values) -> ScenarioOutcome:
    defaults = {
        "scenario_key": key,
        "scenario_version": 1,
        "title": f"Scenario {key}",
        "category": "baseline",
        "agent_quality": agent,
        "platform_assertions": platform,
        "status": "completed",
        "verdict": "passed",
        "score": 100,
        "policy_gate_passed": True,
        "outcome_signature": f"sig-{key}",
        "performance": ScenarioPerformance(
            active_elapsed_ms=40,
            tool_requests=8,
            tool_failures=0,
            denied_requests=0,
            total_tool_ms=12,
        ),
    }
    return ScenarioOutcome(**(defaults | values))


def manifest(*scenarios: ScenarioOutcome, **values) -> BenchmarkManifest:
    defaults = {
        "benchmark_run_id": uuid4(),
        "label": "Test benchmark",
        "grader_version": 1,
        "seed": 42,
        "agent_id": uuid4(),
        "scenario_versions": {s.scenario_key: s.scenario_version for s in scenarios},
        "status": "completed",
        "scenarios": list(scenarios),
        "created_at": NOW,
        "updated_at": NOW,
    }
    built = BenchmarkManifest(**(defaults | values))
    return built.model_copy(update={"gates": compute_gates(built.scenarios)})


def test_store_round_trip_is_sealed(tmp_path):
    store = ManifestStore(tmp_path)
    written = store.write(manifest(outcome()))

    loaded = store.load(written.benchmark_run_id)

    assert loaded == written
    assert loaded.checksum == loaded.computed_checksum()
    assert not list(tmp_path.glob("*/.manifest-*.tmp"))


def test_tampered_manifest_is_rejected(tmp_path):
    store = ManifestStore(tmp_path)
    written = store.write(manifest(outcome(score=55, verdict="failed")))
    path = store.path_for(written.benchmark_run_id)
    data = json.loads(path.read_text())
    data["scenarios"][0]["score"] = 100
    path.write_text(json.dumps(data))

    with pytest.raises(ManifestCorruptError):
        store.load(written.benchmark_run_id)

    manifests, corrupt = store.list()
    assert manifests == []
    assert corrupt == [str(written.benchmark_run_id)]


def test_truncated_or_incompatible_manifest_is_rejected(tmp_path):
    store = ManifestStore(tmp_path)
    broken, incompatible = uuid4(), uuid4()
    for identifier, content in (
        (broken, '{"schema_version": 1, "benchmark'),
        (incompatible, json.dumps({"schema_version": 99})),
    ):
        path = store.path_for(identifier)
        path.parent.mkdir(parents=True)
        path.write_text(content)
        with pytest.raises(ManifestCorruptError):
            store.load(identifier)


def test_missing_manifest_and_path_traversal(tmp_path):
    store = ManifestStore(tmp_path)

    with pytest.raises(ManifestNotFoundError):
        store.load(uuid4())
    with pytest.raises(ValueError):
        store.path_for("../../etc")  # type: ignore[arg-type]


def test_all_passing_suite_passes_both_gates():
    gates = compute_gates([outcome("B01"), outcome("F02"), outcome("S02", agent=False)])

    assert gates.platform.status == "passed"
    assert gates.agent_quality.status == "passed"
    assert gates.overall.status == "passed"
    assert "does not authorize production" in gates.overall.reasons[0]


def test_safety_violation_fails_gate_even_with_full_score():
    gates = compute_gates([outcome("B01", policy_gate_passed=False, score=100)])

    assert gates.platform.status == "failed"
    assert gates.agent_quality.status == "failed"
    assert gates.overall.status == "failed"


def test_missing_or_inconclusive_evidence_blocks_gates():
    interrupted = compute_gates(
        [outcome("B01"), outcome("F01", status="interrupted", verdict=None, score=None)]
    )
    inconclusive = compute_gates([outcome("B01", verdict="inconclusive")])

    assert interrupted.overall.status == "blocked"
    assert "F01 is interrupted" in interrupted.agent_quality.reasons
    assert inconclusive.agent_quality.status == "blocked"


def test_agent_pass_rate_below_threshold_fails_gate():
    gates = compute_gates([outcome("B01"), outcome("F01", verdict="failed", score=40)])

    assert gates.agent_quality.status == "failed"
    assert gates.platform.status == "passed"


def test_failed_platform_only_scenario_fails_platform_gate():
    gates = compute_gates([outcome("S02", agent=False, verdict="failed", score=60)])

    assert gates.platform.status == "failed"
    assert gates.agent_quality.status == "not_run"


def test_comparison_detects_regression_and_reproduction():
    baseline = manifest(outcome("B01"), outcome("F01"))
    same = manifest(outcome("B01"), outcome("F01"))
    worse = manifest(
        outcome("B01"),
        outcome("F01", verdict="failed", score=55, outcome_signature="different"),
    )

    stable = compare_benchmarks(baseline, same)
    regressed = compare_benchmarks(baseline, worse)

    assert stable["regression"] is False
    assert stable["fully_reproduced"] is True
    assert regressed["regression"] is True
    assert regressed["regressed_scenarios"] == ["F01"]
    assert regressed["fully_reproduced"] is False
    f01 = next(row for row in regressed["scenarios"] if row["scenario_key"] == "F01")
    assert f01["score_delta"] == -45


def test_changed_scenario_version_is_not_compared_as_regression():
    baseline = manifest(outcome("B01", score=100))
    candidate = manifest(outcome("B01", scenario_version=2, score=50, verdict="failed"))

    row = compare_benchmarks(baseline, candidate)["scenarios"][0]

    assert row["comparable"] is False
    assert row["regression"] is False
    assert "scenario version changed" in row["notes"]


def test_incompatible_benchmarks_are_rejected():
    with pytest.raises(IncomparableBenchmarksError):
        compare_benchmarks(manifest(outcome()), manifest(outcome(), grader_version=2))


def test_markdown_report_states_scope_and_reproduction():
    report = markdown_report(manifest(outcome("B01"), outcome("S02", agent=False)))

    assert "not a general measure of production safety" in report
    assert "| B01 v1" in report
    assert "--replay" in report


def test_percentile_uses_measured_values_only():
    assert percentile([], 0.95) is None
    assert percentile([5], 0.5) == 5
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.5) == 5
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.95) == 10


def test_harness_injection_cannot_target_read_tools():
    with pytest.raises(ValueError):
        HarnessInjection(after_step=0, tool_name="get_incident", arguments={})
    HarnessInjection(after_step=0, tool_name="delete_database", arguments={})
