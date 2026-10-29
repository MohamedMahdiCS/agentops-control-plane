"""Versioned benchmark manifests with atomic, checksummed persistence.

PostgreSQL is authoritative for runs, evidence and evaluations. The manifest
is authoritative for the intended scenario set, execution configuration and
benchmark progress. Every write replaces the whole file atomically.
"""

import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

MANIFEST_SCHEMA_VERSION: Literal[1] = 1
SUITE_VERSION = "1.0"
SIMULATOR_VERSION = "1.0"

ScenarioStatus = Literal[
    "pending", "running", "completed", "failed", "interrupted", "skipped"
]
BenchmarkStatus = Literal["pending", "running", "completed", "interrupted"]
GateStatus = Literal["passed", "failed", "blocked", "not_run"]


class ManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScenarioPerformance(ManifestModel):
    """Measured locally from persisted run telemetry; never estimated."""

    active_elapsed_ms: int = Field(ge=0)
    wall_elapsed_ms: int | None = Field(default=None, ge=0)
    tool_requests: int = Field(ge=0)
    tool_failures: int = Field(ge=0)
    denied_requests: int = Field(ge=0)
    tool_latency_p50_ms: int | None = Field(default=None, ge=0)
    tool_latency_p95_ms: int | None = Field(default=None, ge=0)
    tool_latency_max_ms: int | None = Field(default=None, ge=0)
    total_tool_ms: int = Field(ge=0)


class ScenarioOutcome(ManifestModel):
    scenario_key: str
    scenario_version: int = Field(ge=1)
    title: str
    category: str
    agent_quality: bool
    platform_assertions: bool
    status: ScenarioStatus = "pending"
    run_id: UUID | None = None
    evaluation_id: UUID | None = None
    run_status: str | None = None
    error_code: str | None = None
    verdict: Literal["passed", "failed", "inconclusive"] | None = None
    score: int | None = Field(default=None, ge=0, le=100)
    policy_gate_passed: bool | None = None
    evidence_fingerprint: str | None = None
    outcome_signature: str | None = None
    performance: ScenarioPerformance | None = None
    harness_notes: list[str] = Field(default_factory=list)
    failure: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class GateDecision(ManifestModel):
    status: GateStatus
    reasons: list[str]


class ReleaseGates(ManifestModel):
    platform: GateDecision
    agent_quality: GateDecision
    overall: GateDecision


class BenchmarkManifest(ManifestModel):
    schema_version: Literal[1] = MANIFEST_SCHEMA_VERSION
    benchmark_run_id: UUID
    label: str = Field(min_length=1, max_length=80)
    suite_version: str = SUITE_VERSION
    simulator_version: str = SIMULATOR_VERSION
    grader_version: int
    execution_mode: Literal["deterministic"] = "deterministic"
    seed: int
    agent_id: UUID
    agent_config_version: int | None = None
    git_commit_sha: str | None = None
    git_dirty: bool | None = None
    replay_of: UUID | None = None
    scenario_versions: dict[str, int]
    status: BenchmarkStatus = "pending"
    scenarios: list[ScenarioOutcome]
    gates: ReleaseGates | None = None
    created_at: datetime
    updated_at: datetime
    checksum: str | None = None

    def computed_checksum(self) -> str:
        payload = self.model_dump(mode="json", exclude={"checksum"})
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ManifestNotFoundError(LookupError):
    pass


class ManifestCorruptError(ValueError):
    """The manifest is unreadable, invalid, incompatible or was modified."""


class ManifestStore:
    def __init__(self, root: Path):
        self.root = root

    def path_for(self, benchmark_run_id: UUID) -> Path:
        # UUID formatting prevents path traversal through identifiers.
        return self.root / str(UUID(str(benchmark_run_id))) / "manifest.json"

    def write(self, manifest: BenchmarkManifest) -> BenchmarkManifest:
        sealed = manifest.model_copy(update={"checksum": None})
        sealed = sealed.model_copy(update={"checksum": sealed.computed_checksum()})
        target = self.path_for(sealed.benchmark_run_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(sealed.model_dump(mode="json"), indent=2, sort_keys=True)

        descriptor, temp_name = tempfile.mkstemp(
            dir=target.parent, prefix=".manifest-", suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(content + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return sealed

    def load(self, benchmark_run_id: UUID) -> BenchmarkManifest:
        target = self.path_for(benchmark_run_id)
        if not target.is_file():
            raise ManifestNotFoundError(benchmark_run_id)
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
            manifest = BenchmarkManifest.model_validate(raw)
        except (OSError, ValueError, ValidationError) as exc:
            raise ManifestCorruptError(str(benchmark_run_id)) from exc
        if manifest.checksum != manifest.computed_checksum():
            raise ManifestCorruptError(f"{benchmark_run_id}: checksum mismatch")
        if manifest.benchmark_run_id != UUID(str(benchmark_run_id)):
            raise ManifestCorruptError(f"{benchmark_run_id}: identifier mismatch")
        return manifest

    def list(self) -> tuple[list[BenchmarkManifest], list[str]]:
        """Return valid manifests newest first and identifiers that failed checks."""
        manifests, corrupt = [], []
        if not self.root.is_dir():
            return [], []
        for entry in self.root.iterdir():
            if not (entry / "manifest.json").is_file():
                continue
            try:
                manifests.append(self.load(UUID(entry.name)))
            except (ValueError, ManifestCorruptError):
                corrupt.append(entry.name)
        manifests.sort(key=lambda item: item.created_at, reverse=True)
        return manifests, sorted(corrupt)
