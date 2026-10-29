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

from sqlalchemy import select

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
from backend.app.models.agent import Agent
from backend.app.schemas.agent import AgentCreate
from backend.app.services.agent_registry import register_agent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--replay", type=UUID, help="Re-execute a previous benchmark")
    mode.add_argument("--resume", type=UUID, help="Continue an interrupted benchmark")
    parser.add_argument("--agent-id", type=UUID, help="Agent to benchmark")
    parser.add_argument(
        "--ensure-agent",
        metavar="NAME",
        help="Use (or register) an active agent with this name, e.g. in CI",
    )
    parser.add_argument("--scenarios", nargs="+", help="Scenario keys (default: all)")
    parser.add_argument("--label", help="Human-readable benchmark label")
    args = parser.parse_args()
    if not (args.replay or args.resume or args.agent_id or args.ensure_agent):
        parser.error(
            "--agent-id or --ensure-agent is required unless --replay or --resume is given"
        )
    return args


async def ensure_agent(session_factory, name: str) -> UUID:
    async with session_factory() as session:
        existing = await session.scalar(
            select(Agent)
            .where(Agent.name == name, Agent.status == "active")
            .order_by(Agent.created_at)
            .limit(1)
        )
        if existing is not None:
            return existing.id
        agent = await register_agent(
            session, AgentCreate(name=name, agent_type="incident_response")
        )
        return agent.id


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
            agent_id = args.agent_id or await ensure_agent(
                create_session_factory(engine), args.ensure_agent
            )
            manifest = await runner.start(
                agent_id=agent_id, scenario_keys=args.scenarios, label=args.label
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
