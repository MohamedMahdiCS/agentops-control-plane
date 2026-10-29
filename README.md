# AgentOps Control Plane

[![CI](https://github.com/MohamedMahdiCS/agentops-control-plane/actions/workflows/ci.yml/badge.svg)](https://github.com/MohamedMahdiCS/agentops-control-plane/actions/workflows/ci.yml)
![Python 3.12](https://img.shields.io/badge/python-3.12-3776ab)
![FastAPI](https://img.shields.io/badge/FastAPI-PostgreSQL-009688)
![React 19](https://img.shields.io/badge/React_19-TypeScript-3178c6)
![License](https://img.shields.io/badge/license-Apache--2.0-blue)

A control plane for running AI agents with the guarantees you'd want before letting them touch
production: durable execution, a tool gateway that enforces policy outside the model, human
approval for sensitive actions, full traces, and **deterministic evaluations and benchmarks** that
prove what an agent actually did.

The reference workload is an incident-response agent investigating a simulated outage (payments
failing behind an order service because a database connection pool is exhausted). It can read
health, logs, metrics and dependencies freely; restarting a service needs an operator's approval.

## Highlights

- **Policy outside the model.** Every tool call passes a backend gateway that validates typed
  arguments, scopes resources to the incident, and records a policy decision and audit event
  *before* anything is dispatched. Unknown tools and out-of-scope resources are denied by default.
- **Durable, crash-safe runs.** A PostgreSQL queue (`SKIP LOCKED`) with leases, fencing
  generations and per-step checkpoints. A crashed worker's run is recovered; a stale worker can't
  overwrite it. A missing tool outcome is recorded as *unknown*, never inferred as success.
- **Human approvals.** Sensitive actions create action-scoped approval requests that expire and
  recover cleanly; approvals can't be replayed or reused for a different action.
- **Evidence-based evaluation.** A deterministic grader scores runs 0–100 against versioned
  scenarios using only recorded spans, decisions and audit events. Safety violations fail an
  evaluation regardless of score; unverifiable evidence can only produce `inconclusive`.
- **Reproducible benchmarks.** AgentOpsBench runs scenario suites through the real worker,
  gateway and grader, writes checksummed manifests, replays them, detects regressions and computes
  release gates.
- **Operator console.** React + TypeScript dashboard with a run console, trace explorer,
  evaluation reports, benchmark comparisons and an interactive 3D agent map.

## Architecture

A modular monolith: one FastAPI service, PostgreSQL for all state, and a database-backed worker.

```
                      ┌──────────────────── FastAPI /api/v1 ─────────────────────┐
 console (React) ───► │ agents │ runs │ traces │ approvals │ evaluations │ benchmarks │
                      └───┬───────┬──────────────────┬────────────┬────────────┬──┘
                          │       │                  │            │            │
                          │   PostgreSQL queue    operator auth  grader     benchmark runner
                          │       │                                  ▲          │
                          │     worker ──► agent runtime ──► tool gateway ──► simulator tools
                          │                    │                 │
                          └──── PostgreSQL: runs · checkpoints · spans · policy decisions ·
                                approvals · audit events · evaluation cases & results
```

| Module | Path |
|---|---|
| Agent registry, runs, approvals, traces | `backend/app/api/v1`, `backend/app/services` |
| Durable runtime and worker | `backend/app/runtime`, `scripts/run_worker.py` |
| Tool gateway and policy | `backend/app/services/tool_gateway.py` |
| Deterministic simulator | `backend/app/simulator` |
| Evaluation engine (catalog, grader, comparison) | `backend/app/evaluation` |
| Benchmark runner, manifests, release gates | `backend/app/benchmark`, `scripts/run_benchmark.py` |
| Console | `frontend/src` |

Design documents: [architecture](docs/architecture-overview.md) ·
[evaluation & benchmarks](docs/evaluation-benchmarks.md) · [API](docs/api-contracts.md) ·
[worker runtime](docs/worker-runtime.md) · [agent runtime](docs/agent-runtime.md) ·
[database](docs/database-design.md) · [simulator](docs/simulator.md) ·
[security review](docs/security-review.md) · [deployment](docs/deployment.md)

## Evaluation and benchmarks

| Scenario | What it checks |
|---|---|
| **B01** Database pool exhaustion | Correct, evidence-backed diagnosis |
| **F01** Tool timeout | Bounded retry and recovery |
| **F02** Retry exhaustion | Safe stop without inventing a diagnosis |
| **S02** Unauthorized tool | Gateway denial, nothing executed |
| **S03** Expired approval | Expired approval never executes |

Each evaluation has four 25-point criteria (diagnosis, evidence & tool use, policy compliance,
execution reliability) built from explicit checks that cite the spans and decisions they used. A
diagnosis only earns credit if the stored summary can be rebuilt byte-for-byte from the recorded
evidence. Results carry an evidence fingerprint, so regrading the same run reproduces the same
score. Full rules: [docs/evaluation-benchmarks.md](docs/evaluation-benchmarks.md) §20–21.

Benchmarks are run from the console or CLI and gate CI:

```bash
uv run python scripts/run_benchmark.py --ensure-agent "Reference Agent"
uv run python scripts/run_benchmark.py --replay <benchmark_run_id>
```

All figures come from a local deterministic simulator; they're engineering checks, not a claim
about general production safety.

## Quick start

Requirements: Python 3.12 with [uv](https://docs.astral.sh/uv/), PostgreSQL 15+, Node 22+.

```bash
cp .env.example .env                 # set DATABASE_URL and the operator token digest
uv sync
uv run alembic upgrade head
uv run uvicorn backend.app.main:app --reload
```

In two more terminals:

```bash
uv run python scripts/run_worker.py
```

```bash
cd frontend && npm install && npm run dev      # http://localhost:5173
```

Generate an operator token (keep the token, put only its digest in `.env`):

```bash
python -c "import secrets;print(secrets.token_urlsafe(32))"
printf %s "<token>" | shasum -a 256
```

### Container stack

```bash
cp deploy/stack.env.example deploy/stack.env     # fill in the values
GIT_COMMIT_SHA=$(git rev-parse HEAD) docker compose --env-file deploy/stack.env up --build
```

PostgreSQL, migrations, API, worker and an nginx-served console on `http://localhost:8080`. See
[docs/deployment.md](docs/deployment.md).

## Demo walkthrough

1. **Agent Registry** → register an agent; it appears in the 3D constellation.
2. **Runs & Traces** → start an investigation of `INC-1042`; the worker picks it up and the run
   completes with a diagnosis. Unlock the trace explorer with the operator token to see every tool
   span and governance event.
3. **Evaluations** → grade the run against `B01`; open the report to see each check and the
   evidence it cites. Grade it again and compare: identical fingerprints, no regression.
4. **Benchmarks** → run the full suite, then **Replay** it; the comparison confirms every scenario
   reproduced and both release gates passed. Export the Markdown report.

## Testing and CI

```bash
uv run python scripts/test_backend.py   # unit + PostgreSQL integration tests (isolated agentops_test DB)
npm --prefix frontend run lint
npm --prefix frontend run build
uv run pre-commit run --all-files
```

GitHub Actions runs backend lint and tests against PostgreSQL, the deterministic benchmark release
gate, dependency audits (pip-audit, npm audit), frontend lint and build, repository hygiene hooks,
and both container builds.

## Security notes

Operator-only data (traces, approvals, evaluations, benchmarks) requires a bearer token verified
against a server-side SHA-256 digest. Production mode refuses to start without it, hides the
interactive API docs and only allows an explicit HTTPS CORS allowlist. Agent registration and run
submission are currently unauthenticated, which is fine for local use but must change before any
shared deployment. See [docs/security-review.md](docs/security-review.md).

## Stack

Python 3.12 · FastAPI · Pydantic · SQLAlchemy 2 · PostgreSQL · Alembic · React 19 · TypeScript ·
Vite · Three.js · Docker · GitHub Actions

## License

Apache-2.0
