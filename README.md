# AgentOps Control Plane

A platform for running AI agents with the controls you'd want before letting them near
production: durable execution, a tool gateway that enforces policy, human approval for sensitive
actions, and a trace of everything the agent did.

The reference scenario is an incident-response agent investigating a simulated outage
(payments failing behind an order service). The agent can read health, logs, metrics and
dependencies freely, but restarting a service needs an operator's approval.

## What works today

| Area | What it does |
|---|---|
| **Agent registry** | Register agents and their configuration (FastAPI + PostgreSQL, Alembic migrations) |
| **Durable runs** | Queued runs are claimed by a PostgreSQL-backed worker using `SKIP LOCKED`, with leases, fencing generations and checkpoints, so a crashed worker's run is recovered and a stale worker can't overwrite it |
| **Incident simulator** | A deterministic environment with a typed tool registry: five read-only diagnostic tools and one sensitive action. Fault injection for timeouts, rate limits and tool errors |
| **Tool gateway** | Every tool call goes through policy checks. Sensitive actions raise an approval request instead of running |
| **Approvals** | Authenticated operators approve or deny; requests expire and recover cleanly |
| **Traces** | Each run records spans for model and tool activity, viewable in an authenticated trace explorer |
| **Console** | React + TypeScript: live agent registry, run console, trace explorer and a 3D view of agent topology |
| **Tests** | 108 tests across the API, database, worker recovery, simulator, gateway policy and auth |

## Planned

- Evaluation engine and AgentOpsBench scoring ([spec](docs/evaluation-benchmarks.md))
- OpenTelemetry export
- Model-driven agents alongside the deterministic test mode

## Architecture

A modular monolith: one FastAPI service with clear module boundaries, PostgreSQL for state, and a
database-backed worker for long-running agent runs.

```
console (React) ──► FastAPI /api/v1 ──► agent registry
                                     ├─► runs ──► PostgreSQL queue ──► worker ──► agent runtime
                                     │                                     └─► tool gateway ──► simulator tools
                                     ├─► approvals (operator auth)            └─► approval requests
                                     └─► traces
```

Design notes: [architecture](docs/architecture-overview.md), [worker runtime](docs/worker-runtime.md),
[agent runtime](docs/agent-runtime.md), [simulator](docs/simulator.md),
[database](docs/database-design.md), [API contracts](docs/api-contracts.md).

## Run it locally

Needs Python 3.12 with [uv](https://docs.astral.sh/uv/), PostgreSQL and Node.

```bash
cp .env.example .env            # set DATABASE_URL
uv sync
uv run alembic upgrade head
uv run uvicorn backend.app.main:app --reload
```

```bash
cd frontend && npm install && npm run dev
```

Tests:

```bash
uv run pytest
```

## Stack

Python 3.12 · FastAPI · Pydantic · SQLAlchemy · PostgreSQL · Alembic · React · TypeScript · Vite

## License

Apache-2.0
