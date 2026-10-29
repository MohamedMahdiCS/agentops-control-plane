"""Run, replay or resume an AgentOpsBench benchmark from the command line.

Examples:
  uv run python scripts/run_benchmark.py --agent-id <uuid>
  uv run python scripts/run_benchmark.py --agent-id <uuid> --scenarios B01 F01
  uv run python scripts/run_benchmark.py --replay <benchmark_run_id>
  uv run python scripts/run_benchmark.py --resume <benchmark_run_id>

Exit status: 0 when the overall release gate passes, 1 when it fails or is
blocked, 2 on usage or configuration errors.
"""

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.benchmark.analysis import markdown_report
from backend.app.benchmark.manifest import ManifestStore
from backend.app.benchmark.runner import (
    PROJECT_ROOT,
    BenchmarkConfigurationError,
    BenchmarkRunner,
)
from backend.app.core.config import Settings
from backend.app.core.database import create_database_engine
from backend.app.core.session import create_session_factory


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--replay", type=UUID, help="Re-execute a previous benchmark")
    mode.add_argument("--resume", type=UUID, help="Continue an interrupted benchmark")
    parser.add_argument("--agent-id", type=UUID, help="Agent to benchmark")
    parser.add_argument("--scenarios", nargs="+", help="Scenario keys (default: all)")
    parser.add_argument("--label", help="Human-readable benchmark label")
    args = parser.parse_args()
    if not (args.replay or args.resume or args.agent_id):
        parser.error("--agent-id is required unless --replay or --resume is given")
    return args


async def main() -> int:
    args = parse_args()
    configured = Path(Settings().benchmark_data_dir)
    store = ManifestStore(
        configured if configured.is_absolute() else PROJECT_ROOT / configured
    )
    engine = create_database_engine()
    try:
        runner = BenchmarkRunner(
            create_session_factory(engine), store, operator_id="benchmark-cli"
        )
        if args.replay:
            manifest = await runner.replay(args.replay, label=args.label)
        elif args.resume:
            manifest = await runner.resume(args.resume)
        else:
            manifest = await runner.start(
                agent_id=args.agent_id, scenario_keys=args.scenarios, label=args.label
            )
    except BenchmarkConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    finally:
        await engine.dispose()

    print(markdown_report(manifest))
    print(f"Manifest: {store.path_for(manifest.benchmark_run_id)}")
    return 0 if manifest.gates and manifest.gates.overall.status == "passed" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
