"""Operator-authenticated benchmark execution, replay and comparison."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import PlainTextResponse

from backend.app.benchmark.analysis import (
    IncomparableBenchmarksError,
    compare_benchmarks,
    markdown_report,
    performance_summary,
)
from backend.app.benchmark.manifest import (
    BenchmarkManifest,
    ManifestCorruptError,
    ManifestNotFoundError,
    ManifestStore,
    configured_store,
)
from backend.app.benchmark.runner import (
    BenchmarkBusyError,
    BenchmarkConfigurationError,
    BenchmarkRunner,
)
from backend.app.core.operator_auth import OperatorPrincipal, require_operator
from backend.app.schemas.benchmarks import (
    BenchmarkComparison,
    BenchmarkCreate,
    BenchmarkDetail,
    BenchmarkListResponse,
    BenchmarkReplay,
    BenchmarkSummary,
    PerformanceSummary,
)

router = APIRouter(prefix="/benchmarks", tags=["Benchmarks"])

Operator = Annotated[OperatorPrincipal, Depends(require_operator)]


def get_manifest_store(principal: Operator) -> ManifestStore:
    return configured_store()


Store = Annotated[ManifestStore, Depends(get_manifest_store)]


def get_runner(request: Request, principal: Operator, store: Store) -> BenchmarkRunner:
    return BenchmarkRunner(
        request.app.state.db_session_factory,
        store,
        operator_id=principal.operator_id,
    )


Runner = Annotated[BenchmarkRunner, Depends(get_runner)]


def detail(manifest: BenchmarkManifest) -> BenchmarkDetail:
    return BenchmarkDetail(
        manifest=manifest,
        performance=PerformanceSummary.model_validate(performance_summary(manifest)),
    )


def load(store: ManifestStore, benchmark_run_id: UUID) -> BenchmarkManifest:
    try:
        return store.load(benchmark_run_id)
    except ManifestNotFoundError as exc:
        raise HTTPException(404, "Benchmark run not found") from exc
    except ManifestCorruptError as exc:
        raise HTTPException(
            409, "Benchmark manifest failed integrity validation"
        ) from exc


async def run_guarded(operation) -> BenchmarkManifest:
    try:
        return await operation
    except BenchmarkBusyError as exc:
        raise HTTPException(409, "Another benchmark is already running") from exc
    except BenchmarkConfigurationError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ManifestNotFoundError as exc:
        raise HTTPException(404, "Benchmark run not found") from exc
    except ManifestCorruptError as exc:
        raise HTTPException(
            409, "Benchmark manifest failed integrity validation"
        ) from exc


@router.get("", response_model=BenchmarkListResponse)
async def list_benchmarks(store: Store) -> BenchmarkListResponse:
    manifests, corrupt = store.list()
    summaries = []
    for manifest in manifests[:100]:
        scenarios = manifest.scenarios
        summaries.append(
            BenchmarkSummary(
                benchmark_run_id=manifest.benchmark_run_id,
                label=manifest.label,
                status=manifest.status,
                gate=manifest.gates.overall.status if manifest.gates else "not_run",
                replay_of=manifest.replay_of,
                scenario_count=len(scenarios),
                passed=sum(s.verdict == "passed" for s in scenarios),
                failed=sum(s.verdict == "failed" for s in scenarios),
                inconclusive=sum(s.verdict == "inconclusive" for s in scenarios),
                incomplete=sum(s.status != "completed" for s in scenarios),
                git_commit_sha=manifest.git_commit_sha,
                created_at=manifest.created_at,
            )
        )
    return BenchmarkListResponse(benchmarks=summaries, corrupt_manifests=corrupt)


@router.post("", response_model=BenchmarkDetail, status_code=status.HTTP_201_CREATED)
async def start_benchmark(
    payload: BenchmarkCreate, response: Response, runner: Runner
) -> BenchmarkDetail:
    manifest = await run_guarded(
        runner.start(
            agent_id=payload.agent_id,
            scenario_keys=payload.scenario_keys,
            label=payload.label,
        )
    )
    response.headers["Location"] = f"/api/v1/benchmarks/{manifest.benchmark_run_id}"
    return detail(manifest)


@router.get("/{benchmark_run_id}", response_model=BenchmarkDetail)
async def get_benchmark(benchmark_run_id: UUID, store: Store) -> BenchmarkDetail:
    return detail(load(store, benchmark_run_id))


@router.post(
    "/{benchmark_run_id}/replay",
    response_model=BenchmarkDetail,
    status_code=status.HTTP_201_CREATED,
)
async def replay_benchmark(
    benchmark_run_id: UUID,
    payload: BenchmarkReplay,
    response: Response,
    runner: Runner,
) -> BenchmarkDetail:
    manifest = await run_guarded(runner.replay(benchmark_run_id, label=payload.label))
    response.headers["Location"] = f"/api/v1/benchmarks/{manifest.benchmark_run_id}"
    return detail(manifest)


@router.post("/{benchmark_run_id}/resume", response_model=BenchmarkDetail)
async def resume_benchmark(benchmark_run_id: UUID, runner: Runner) -> BenchmarkDetail:
    return detail(await run_guarded(runner.resume(benchmark_run_id)))


@router.get("/{benchmark_run_id}/compare", response_model=BenchmarkComparison)
async def compare(
    benchmark_run_id: UUID,
    store: Store,
    baseline_id: Annotated[UUID, Query()],
) -> BenchmarkComparison:
    candidate = load(store, benchmark_run_id)
    baseline = load(store, baseline_id)
    try:
        return BenchmarkComparison.model_validate(
            compare_benchmarks(baseline, candidate)
        )
    except IncomparableBenchmarksError as exc:
        raise HTTPException(422, f"Benchmarks are not comparable: {exc}") from exc


@router.get("/{benchmark_run_id}/report.md", response_class=PlainTextResponse)
async def report(
    benchmark_run_id: UUID,
    store: Store,
    baseline_id: Annotated[UUID | None, Query()] = None,
) -> PlainTextResponse:
    manifest = load(store, benchmark_run_id)
    comparison = None
    if baseline_id is not None:
        try:
            comparison = compare_benchmarks(load(store, baseline_id), manifest)
        except IncomparableBenchmarksError as exc:
            raise HTTPException(422, f"Benchmarks are not comparable: {exc}") from exc
    return PlainTextResponse(
        markdown_report(manifest, comparison), media_type="text/markdown"
    )
