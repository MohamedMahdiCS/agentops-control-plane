"""Populate a local demo database by running the real system.

Every agent, run, evaluation and benchmark is produced by the actual worker,
Tool Gateway, grader and benchmark runner; nothing is inserted by hand.

  createdb agentops_demo
  DATABASE_URL=postgresql://localhost/agentops_demo uv run alembic upgrade head
  DATABASE_URL=postgresql://localhost/agentops_demo \
    uv run python scripts/demo/seed_demo.py data/benchmarks/demo

Refuses to run against any database not named agentops_demo.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sqlalchemy import update

from backend.app.benchmark.manifest import ManifestStore
from backend.app.benchmark.runner import BenchmarkRunner
from backend.app.core.config import Settings
from backend.app.core.database import create_database_engine
from backend.app.core.session import create_session_factory
from backend.app.evaluation.catalog import latest_scenario
from backend.app.models.agent import Agent
from backend.app.runtime.runner import run_worker_once
from backend.app.runtime.worker import HarnessInjection
from backend.app.schemas.agent import AgentCreate
from backend.app.schemas.agent_run import AgentRunCreate
from backend.app.services.agent_registry import register_agent
from backend.app.services.agent_runs import create_agent_run
from backend.app.services.evaluations import evaluate_run, sync_catalog
from backend.app.simulator.faults import FaultInjectingSimulator

if not Settings().database_url.get_secret_value().endswith("/agentops_demo"):
    sys.exit("Refusing to seed: DATABASE_URL must point at agentops_demo")


async def main(store_dir):
    engine = create_database_engine()
    f = create_session_factory(engine)
    async with f() as s:
        await sync_catalog(s)
    agents = {}
    for name, desc in [
        ("Production Incident Agent", "Investigates production incidents"),
        ("Staging Incident Agent", "Validates changes before release"),
        ("Canary Incident Agent", "Watches canary deployments"),
        ("Payments Triage Agent", "Triage for payment failures"),
        ("Legacy Incident Agent", "Retired v0 agent"),
    ]:
        async with f() as s:
            agents[name] = await register_agent(
                s,
                AgentCreate(
                    name=name, description=desc, agent_type="incident_response"
                ),
            )
    async with f() as s, s.begin():
        await s.execute(
            update(Agent)
            .where(Agent.id == agents["Legacy Incident Agent"].id)
            .values(status="disabled")
        )

    async def run(agent, scenario=None, injection=None):
        async with f() as s:
            r = await create_agent_run(
                s, agent.id, AgentRunCreate(incident_id="INC-1042")
            )
        faults = (
            list(latest_scenario(scenario).scenario_config.faults) if scenario else []
        )
        await run_worker_once(
            f,
            "demo-worker-1",
            run_id=r.id,
            tool_invoker=FaultInjectingSimulator(faults).invoke,
            injection=injection,
        )
        return r.id

    async def grade(run_id, key):
        async with f() as s:
            res = (
                await evaluate_run(
                    s,
                    run_id=run_id,
                    scenario_key=key,
                    scenario_version=None,
                    operator_id="demo-operator",
                )
            ).result
        print(f"  {key} -> {res.verdict} {res.score}")

    prod, stag, can, pay = (
        agents[n]
        for n in [
            "Production Incident Agent",
            "Staging Incident Agent",
            "Canary Incident Agent",
            "Payments Triage Agent",
        ]
    )
    for agent in (prod, stag, can, pay):
        await grade(await run(agent), "B01")
    await grade(await run(prod, "F01"), "F01")
    await grade(await run(stag, "F01"), "F01")
    stop = await run(can, "F02")
    await grade(stop, "F02")
    await grade(stop, "B01")
    await grade(await run(pay), "B01")
    # One run waits on a human: the harness requests a restart after the investigation.
    await run(
        prod,
        injection=HarnessInjection(
            after_step=8,
            tool_name="restart_service",
            arguments={
                "service_name": "payment-service",
                "reason": "Restart after confirming connection exhaustion.",
            },
        ),
    )
    store = ManifestStore(Path(store_dir))
    runner = BenchmarkRunner(f, store, operator_id="demo-operator")
    m = await runner.start(agent_id=prod.id, label="Release candidate v1.4")
    r = await runner.replay(m.benchmark_run_id, label="Replay: release candidate v1.4")
    print("benchmark", m.gates.overall.status, "replay", r.gates.overall.status)
    await engine.dispose()


asyncio.run(main(sys.argv[1]))
