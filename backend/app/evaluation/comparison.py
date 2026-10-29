"""Deterministic regression comparison between two stored evaluations.

Only results for the same scenario version and grader version are compared;
anything else would compare different rubrics and is rejected.
"""

from dataclasses import dataclass
from typing import Any, Literal

Change = Literal["improved", "regressed", "unchanged"]

VERDICT_RANK = {"failed": 0, "inconclusive": 1, "passed": 2}
CHECK_RANK = {"failed": 0, "unknown": 1, "not_applicable": 2, "passed": 3}


class IncomparableEvaluationsError(ValueError):
    pass


@dataclass(frozen=True)
class StoredEvaluation:
    scenario_key: str
    case_version: int
    grader_version: int
    verdict: str | None
    score: int | None
    criteria_results: dict[str, Any]


def _change(before: int, after: int) -> Change:
    if after > before:
        return "improved"
    if after < before:
        return "regressed"
    return "unchanged"


def _checks(result: StoredEvaluation) -> dict[tuple[str, str], dict[str, Any]]:
    checks = {}
    for criterion in result.criteria_results.get("criteria", []):
        for check in criterion.get("checks", []):
            checks[(criterion["key"], check["key"])] = check
    return checks


def _criteria(result: StoredEvaluation) -> dict[str, dict[str, Any]]:
    return {c["key"]: c for c in result.criteria_results.get("criteria", [])}


def _violations(result: StoredEvaluation) -> set[str]:
    gate = result.criteria_results.get("safety_gate") or {}
    return set(gate.get("violations", []))


def compare_evaluations(
    baseline: StoredEvaluation, candidate: StoredEvaluation
) -> dict[str, Any]:
    reasons = []
    if baseline.scenario_key != candidate.scenario_key:
        reasons.append("different scenarios")
    if baseline.case_version != candidate.case_version:
        reasons.append("different scenario versions")
    if baseline.grader_version != candidate.grader_version:
        reasons.append("different grader versions")
    if reasons:
        raise IncomparableEvaluationsError(", ".join(reasons))

    verdict_change = _change(
        VERDICT_RANK.get(baseline.verdict or "", -1),
        VERDICT_RANK.get(candidate.verdict or "", -1),
    )
    score_delta = (
        candidate.score - baseline.score
        if baseline.score is not None and candidate.score is not None
        else None
    )

    base_criteria, cand_criteria = _criteria(baseline), _criteria(candidate)
    criteria = []
    for key, cand in cand_criteria.items():
        base = base_criteria.get(key, {})
        before, after = base.get("score"), cand.get("score")
        criteria.append(
            {
                "key": key,
                "title": cand.get("title", key),
                "baseline_score": before,
                "candidate_score": after,
                "delta": after - before
                if before is not None and after is not None
                else None,
            }
        )

    base_checks, cand_checks = _checks(baseline), _checks(candidate)
    checks = []
    for (criterion_key, check_key), cand in cand_checks.items():
        prior = base_checks.get((criterion_key, check_key))
        before = prior["status"] if prior else "not_applicable"
        after = cand["status"]
        checks.append(
            {
                "criterion": criterion_key,
                "key": check_key,
                "title": cand["title"],
                "baseline_status": before,
                "candidate_status": after,
                "change": _change(CHECK_RANK[before], CHECK_RANK[after]),
            }
        )

    base_violations, cand_violations = _violations(baseline), _violations(candidate)
    new_violations = sorted(cand_violations - base_violations)
    regressed_checks = [c for c in checks if c["change"] == "regressed"]

    regression = (
        verdict_change == "regressed"
        or (score_delta is not None and score_delta < 0)
        or bool(new_violations)
        or bool(regressed_checks)
    )

    return {
        "scenario_key": candidate.scenario_key,
        "case_version": candidate.case_version,
        "grader_version": candidate.grader_version,
        "baseline_verdict": baseline.verdict,
        "candidate_verdict": candidate.verdict,
        "verdict_change": verdict_change,
        "baseline_score": baseline.score,
        "candidate_score": candidate.score,
        "score_delta": score_delta,
        "regression": regression,
        "same_evidence": baseline.criteria_results.get("evidence_fingerprint")
        == candidate.criteria_results.get("evidence_fingerprint"),
        "new_safety_violations": new_violations,
        "resolved_safety_violations": sorted(base_violations - cand_violations),
        "criteria": criteria,
        "checks": checks,
    }
