"""Reproducible AgentOpsBench execution and replay.

Each scenario runs through the production worker, Tool Gateway and grader.
Stable, scoped idempotency keys make every database step safe to repeat, so
an interrupted benchmark resumes without duplicating runs, evaluations or
simulated side effects.
"""

import fcntl
import hashlib
import json
import logging
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.benchmark.analysis import compute_gates, percentile
from backend.app.benchmark.manifest import (
    BenchmarkManifest,
    ManifestStore,
    ScenarioOutcome,
    ScenarioPerformance,
)
from backend.app.evaluation.catalog import (
    GRADER_VERSION,
    SCENARIOS,
    ScenarioDefinition,
    latest_scenario,
    scenario_index,
)
from backend.app.evaluation.grader import RunEvidence
from backend.app.models.agent import Agent
from backend.app.models.agent_run import AgentRun
from backend.app.models.approval_request import ApprovalRequest
from backend.app.models.trace_span import TraceSpan
from backend.app.runtime.runner import run_worker_once
from backend.app.runtime.worker import HarnessInjection
from backend.app.schemas.agent_run import AgentRunCreate
from backend.app.services.agent_runs import create_agent_run
from backend.app.services.approval_expiration import expire_pending_approvals
from backend.app.services.evaluations import evaluate_run, load_run_evidence
from backend.app.simulator.faults import FaultInjectingSimulator

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
TERMINAL = {"completed", "failed", "cancelled"}


class BenchmarkBusyError(RuntimeError):
    """Another benchmark runner holds the local execution lock."""


class BenchmarkConfigurationError(ValueError):
    pass


def git_revision() -> tuple[str | None, bool | None]:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=no"],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            ).stdout.strip()
        )
        return sha or None, dirty
    except (OSError, subprocess.SubprocessError):
        return None, None


@contextmanager
def runner_lock(root: Path) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    with open(root / ".runner.lock", "w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BenchmarkBusyError("A benchmark is already running") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def outcome_signature(evidence: RunEvidence, criteria_results: dict) -> str:
    """Identifier-free digest of observable behaviour and grading.

    Two executions of the same scenario reproduce each other when their
    signatures match, even though run, span and decision IDs differ.
    """
    run = evidence.run
    checks = [
        [criterion["key"], check["key"], check["status"]]
        for criterion in criteria_results.get("criteria", [])
        for check in criterion.get("checks", [])
    ]
    payload = {
        "run": [run.status, run.error_code, run.result_summary],
        "checkpoint": run.execution_checkpoint,
        "spans": [
            [s.span_type, s.name, s.resource, s.status, s.safe_summary]
            for s in evidence.spans
        ],
        "decisions": [
            [d.action, d.resource, d.decision, d.reason_code, d.executed]
            for d in evidence.decisions
        ],
        "approvals": [[a.status, a.execution_status] for a in evidence.approvals],
        "checks": checks,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def measure(
    evidence: RunEvidence,
    run: AgentRun,
    span_durations: list[int],
) -> ScenarioPerformance:
    tool_spans = [s for s in evidence.spans if s.span_type == "tool_call"]
    wall = (
        int((run.finished_at - run.started_at).total_seconds() * 1000)
        if run.started_at and run.finished_at and run.finished_at >= run.started_at
        else None
    )
    return ScenarioPerformance(
        active_elapsed_ms=run.active_elapsed_ms,
        wall_elapsed_ms=wall,
        tool_requests=len(tool_spans),
        tool_failures=sum(s.status == "error" for s in tool_spans),
        denied_requests=sum(d.decision == "deny" for d in evidence.decisions),
        tool_latency_p50_ms=percentile(span_durations, 0.5),
        tool_latency_p95_ms=percentile(span_durations, 0.95),
        tool_latency_max_ms=max(span_durations) if span_durations else None,
        total_tool_ms=sum(span_durations),
    )


def _now() -> datetime:
    return datetime.now(UTC)


def resolve_scenarios(
    scenario_keys: list[str] | None,
) -> list[ScenarioDefinition]:
    if not scenario_keys:
        keys = sorted({s.scenario_key for s in SCENARIOS})
    else:
        keys = list(dict.fromkeys(scenario_keys))
    definitions = []
    for key in keys:
        definition = latest_scenario(key)
        if definition is None:
            raise BenchmarkConfigurationError(f"Unknown scenario {key}")
        definitions.append(definition)
    return definitions


def new_manifest(
    *,
    agent: Agent,
    scenarios: list[ScenarioDefinition],
    label: str,
    replay_of: UUID | None = None,
) -> BenchmarkManifest:
    sha, dirty = git_revision()
    seeds = {s.scenario_config.seed for s in scenarios}
    now = _now()
    return BenchmarkManifest(
        benchmark_run_id=uuid4(),
        label=label,
        grader_version=GRADER_VERSION,
        seed=seeds.pop() if len(seeds) == 1 else 0,
        agent_id=agent.id,
        agent_config_version=agent.config_version,
        git_commit_sha=sha,
        git_dirty=dirty,
        replay_of=replay_of,
        scenario_versions={s.scenario_key: s.version for s in scenarios},
        scenarios=[
            ScenarioOutcome(
                scenario_key=s.scenario_key,
                scenario_version=s.version,
                title=s.scenario_config.title,
                category=s.category,
                agent_quality=s.scenario_config.agent_quality,
                platform_assertions=s.scenario_config.platform_assertions,
            )
            for s in scenarios
        ],
        created_at=now,
        updated_at=now,
    )


class BenchmarkRunner:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        store: ManifestStore,
        *,
        operator_id: str,
    ):
        self.session_factory = session_factory
        self.store = store
        self.operator_id = operator_id

    async def _agent(self, agent_id: UUID) -> Agent:
        async with self.session_factory() as session:
            agent = await session.get(Agent, agent_id)
        if agent is None:
            raise BenchmarkConfigurationError("Agent not found")
        if agent.status != "active":
            raise BenchmarkConfigurationError("Agent is disabled")
        return agent

    async def start(
        self,
        *,
        agent_id: UUID,
        scenario_keys: list[str] | None = None,
        label: str | None = None,
    ) -> BenchmarkManifest:
        agent = await self._agent(agent_id)
        scenarios = resolve_scenarios(scenario_keys)
        manifest = new_manifest(
            agent=agent,
            scenarios=scenarios,
            label=label or f"Benchmark {_now():%Y-%m-%d %H:%M}",
        )
        return await self.execute(manifest)

    async def replay(
        self, source_id: UUID, *, label: str | None = None
    ) -> BenchmarkManifest:
        """Re-execute the exact scenario versions of a previous benchmark."""
        source = self.store.load(source_id)
        agent = await self._agent(source.agent_id)
        index = scenario_index()
        scenarios = []
        for key, version in source.scenario_versions.items():
            definition = index.get((key, version))
            if definition is None:
                raise BenchmarkConfigurationError(
                    f"Scenario {key} v{version} is no longer published"
                )
            scenarios.append(definition)
        manifest = new_manifest(
            agent=agent,
            scenarios=scenarios,
            label=label or f"Replay of {source.label}"[:80],
            replay_of=source.benchmark_run_id,
        )
        return await self.execute(manifest)

    async def resume(self, benchmark_run_id: UUID) -> BenchmarkManifest:
        """Continue an interrupted benchmark; completed scenarios are preserved."""
        return await self.execute(self.store.load(benchmark_run_id))

    async def execute(self, manifest: BenchmarkManifest) -> BenchmarkManifest:
        with runner_lock(self.store.root):
            index = scenario_index()
            manifest = self.store.write(
                manifest.model_copy(update={"status": "running", "updated_at": _now()})
            )
            for position, outcome in enumerate(manifest.scenarios):
                if outcome.status in ("completed", "skipped"):
                    continue
                definition = index.get((outcome.scenario_key, outcome.scenario_version))
                running = outcome.model_copy(
                    update={"status": "running", "started_at": _now(), "failure": None}
                )
                manifest = self._replace(manifest, position, running)
                try:
                    if definition is None:
                        raise BenchmarkConfigurationError(
                            "Scenario version unavailable"
                        )
                    finished = await self._run_scenario(manifest, running, definition)
                except Exception as exc:  # Recorded in the manifest, never hidden.
                    logger.exception(
                        "Benchmark scenario %s failed", outcome.scenario_key
                    )
                    finished = running.model_copy(
                        update={
                            "status": "failed",
                            "failure": type(exc).__name__,
                            "finished_at": _now(),
                        }
                    )
                manifest = self._replace(manifest, position, finished)

            return self.store.write(
                manifest.model_copy(
                    update={
                        "status": "completed",
                        "gates": compute_gates(manifest.scenarios),
                        "updated_at": _now(),
                    }
                )
            )

    def _replace(
        self, manifest: BenchmarkManifest, position: int, outcome: ScenarioOutcome
    ) -> BenchmarkManifest:
        scenarios = list(manifest.scenarios)
        scenarios[position] = outcome
        return self.store.write(
            manifest.model_copy(update={"scenarios": scenarios, "updated_at": _now()})
        )

    async def _run_scenario(
        self,
        manifest: BenchmarkManifest,
        outcome: ScenarioOutcome,
        definition: ScenarioDefinition,
    ) -> ScenarioOutcome:
        config = definition.scenario_config
        scope = (
            f"bench:{manifest.benchmark_run_id}:"
            f"{definition.scenario_key}:v{definition.version}"
        )
        notes = list(outcome.harness_notes)

        async with self.session_factory() as session:
            run = await create_agent_run(
                session,
                manifest.agent_id,
                AgentRunCreate(incident_id=config.incident_id),
                idempotency_key=scope,
            )
        run_id = run.id
        async with self.session_factory() as session, session.begin():
            await session.execute(
                update(AgentRun)
                .where(AgentRun.id == run_id, AgentRun.benchmark_run_id.is_(None))
                .values(benchmark_run_id=manifest.benchmark_run_id)
            )

        if run.status == "queued":
            injection = (
                HarnessInjection(
                    after_step=config.injection.after_step,
                    tool_name=config.injection.tool_name,
                    arguments=dict(config.injection.arguments),
                )
                if config.injection
                else None
            )
            await run_worker_once(
                self.session_factory,
                worker_id=f"benchmark-{str(manifest.benchmark_run_id)[:8]}",
                run_id=run_id,
                tool_invoker=FaultInjectingSimulator(list(config.faults)).invoke,
                injection=injection,
            )
        else:
            notes.append(f"Reused existing run in status {run.status}")

        if definition.expected_outcome.approval_final_status == "expired":
            advanced = await self._advance_approval_clock(run_id)
            if advanced:
                notes.append(
                    "Harness advanced the approval deadline to the database clock; "
                    "the standard expiration service then expired it"
                )
                await expire_pending_approvals(self.session_factory)

        async with self.session_factory() as session:
            stored = await session.get(AgentRun, run_id, populate_existing=True)
        if stored is None or stored.status not in TERMINAL:
            return outcome.model_copy(
                update={
                    "status": "failed",
                    "run_id": run_id,
                    "run_status": stored.status if stored else None,
                    "failure": "Run did not reach a terminal state",
                    "harness_notes": notes,
                    "finished_at": _now(),
                }
            )

        async with self.session_factory() as session:
            recorded = await evaluate_run(
                session,
                run_id=run_id,
                scenario_key=definition.scenario_key,
                scenario_version=definition.version,
                operator_id=self.operator_id,
                idempotency_key=f"{scope}:eval",
            )
        result = recorded.result

        async with self.session_factory() as session:
            evidence = await load_run_evidence(session, run_id)
            run_row = await session.get(AgentRun, run_id)
            # Only dispatched tool calls have a measured duration.
            durations = [
                duration
                for duration in (
                    await session.scalars(
                        select(TraceSpan.duration_ms).where(
                            TraceSpan.run_id == run_id,
                            TraceSpan.span_type == "tool_call",
                            TraceSpan.duration_ms.is_not(None),
                        )
                    )
                ).all()
                if duration is not None
            ]
        if evidence is None or run_row is None:
            raise RuntimeError("Run evidence disappeared during benchmark")

        return outcome.model_copy(
            update={
                "status": "completed",
                "run_id": run_id,
                "evaluation_id": result.id,
                "run_status": run_row.status,
                "error_code": run_row.error_code,
                "verdict": result.verdict,
                "score": result.score,
                "policy_gate_passed": result.policy_gate_passed,
                "evidence_fingerprint": result.criteria_results.get(
                    "evidence_fingerprint"
                ),
                "outcome_signature": outcome_signature(
                    evidence, result.criteria_results
                ),
                "performance": measure(evidence, run_row, durations),
                "harness_notes": notes,
                "finished_at": _now(),
            }
        )

    async def _advance_approval_clock(self, run_id: UUID) -> bool:
        async with self.session_factory() as session, session.begin():
            advanced = await session.scalars(
                update(ApprovalRequest)
                .where(
                    ApprovalRequest.run_id == run_id,
                    ApprovalRequest.status == "pending",
                )
                .values(expires_at=func.clock_timestamp())
                .returning(ApprovalRequest.id)
            )
            return bool(advanced.all())
