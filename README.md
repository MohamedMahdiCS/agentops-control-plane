<div align="center">

# AgentOps Control Plane

**Run, govern, evaluate and replay AI agents — with every number backed by recorded evidence.**

[![CI](https://github.com/MohamedMahdiCS/agentops-control-plane/actions/workflows/ci.yml/badge.svg)](https://github.com/MohamedMahdiCS/agentops-control-plane/actions/workflows/ci.yml)
![Python 3.12](https://img.shields.io/badge/python-3.12-3776ab)
![FastAPI](https://img.shields.io/badge/FastAPI-PostgreSQL-009688)
![React 19](https://img.shields.io/badge/React_19-TypeScript-3178c6)
![Three.js](https://img.shields.io/badge/Three.js-WebGL-7c6cff)
![License](https://img.shields.io/badge/license-Apache--2.0-blue)

![AgentOps Control Plane overview](docs/assets/screenshots/overview.webp)

</div>

AgentOps Control Plane gives AI agents the guarantees you'd want before letting them near
production: crash-safe execution, a tool gateway that enforces policy outside the model, human
approval for sensitive actions, full traces, and **deterministic evaluations and benchmarks** that
prove what an agent actually did.

The reference workload is an incident-response agent investigating a simulated outage — payments
failing behind an order service because a database connection pool is exhausted. It can read
health, logs, metrics and dependencies freely; restarting a service needs an operator's approval.

## Highlights

- **Policy outside the model.** Every tool call passes a backend gateway that validates typed
  arguments, scopes resources to the incident, and commits a policy decision and audit event
  *before* anything is dispatched. Unknown tools and out-of-scope resources are denied by default.
- **Durable, crash-safe runs.** A PostgreSQL queue (`SKIP LOCKED`) with leases, fencing
  generations and checkpoints. A crashed worker's run is recovered; a stale worker can't overwrite
  it. A missing tool outcome is recorded as *unknown*, never inferred as success.
- **Human approvals.** Sensitive actions create action-scoped approval requests that expire and
  recover cleanly; approvals can't be replayed or reused for a different action.
- **Evidence-based evaluation.** A deterministic grader scores runs 0–100 against versioned
  scenarios using only recorded spans, decisions and audit events. Safety violations fail an
  evaluation regardless of score; unverifiable evidence can only produce `inconclusive`.
- **Reproducible benchmarks.** Scenario suites run through the real worker, gateway and grader,
  write checksummed manifests, replay, detect regressions and compute release gates — in CI too.
- **Operator console.** A "Neural glass" React console: live governance stream, an interactive
  WebGL agent constellation, evaluation reports, benchmark comparisons and a `⌘K` command palette.

## Visual tour

<table>
<tr>
<td width="50%" valign="top">

**Live agent constellation**<br/>
Registered agents orbit the control-plane core. Labels are placed collision-free in screen space;
the scene renders on demand and pauses off-screen.

<img src="docs/assets/screenshots/constellation.gif" alt="Animated agent constellation" />

</td>
<td width="50%" valign="top">

**Regression detection**<br/>
Comparing two evaluations of the same scenario: every criterion and check is diffed, and the
failing run's missing evidence is pinpointed.

<img src="docs/assets/screenshots/evaluation-regression.webp" alt="Evaluation regression comparison" />

</td>
</tr>
<tr>
<td width="50%" valign="top">

**Benchmarks and release gates**<br/>
Five scenarios — diagnosis, timeout recovery, safe stop, unauthorized tool, expired approval —
graded through the real system, with platform and agent-quality gates.

<img src="docs/assets/screenshots/benchmarks.webp" alt="Benchmark release gates and scenario results" />

</td>
<td width="50%" valign="top">

**Trace explorer**<br/>
Every tool span and governance event for a run, in order. Raw arguments, responses and audit
payloads are intentionally excluded from the API.

<img src="docs/assets/screenshots/traces.webp" alt="Run trace explorer timeline" />

</td>
</tr>
<tr>
<td width="50%" valign="top">

**Evaluation engine**<br/>
Versioned scenario catalog, run grading and an append-only history with pass rate, average score
and safety-gate failures.

<img src="docs/assets/screenshots/evaluations.webp" alt="Evaluation dashboard" />

</td>
<td width="50%" valign="top">

**Keyboard-first and responsive**<br/>
`⌘K` jumps anywhere; the console adapts down to phone widths.

<img src="docs/assets/screenshots/command-palette.webp" alt="Command palette" />
<p align="center"><img src="docs/assets/screenshots/mobile.webp" alt="Mobile overview" width="46%" /></p>

</td>
</tr>
</table>

<sub>Screenshots come from the real console against a local demo database populated by
<a href="scripts/demo/seed_demo.py">running the system itself</a> — no mocked values.</sub>

## Architecture

A modular monolith: one FastAPI service, PostgreSQL for all state, and a database-backed worker.

```mermaid
flowchart LR
  subgraph console["Operator console"]
    ui["Overview · Runs · Evaluations · Benchmarks"]
  end
  ui -- "REST /api/v1" --> api["FastAPI"]
  api --> auth{{"Operator auth"}}
  api --> registry["Agent registry"]
  api --> queue[("PostgreSQL run queue")]
  worker["Durable worker<br/>leases · fencing · checkpoints"] -- "SKIP LOCKED claim" --> queue
  worker --> runtime["Agent runtime"]
  runtime --> gateway["Tool gateway<br/>default-deny policy"]
  gateway -- "allowed reads" --> tools["Simulated tools"]
  gateway -- "sensitive actions" --> approvals["Human approvals"]
  gateway --> evidence[("Spans · policy decisions · audit events")]
  api --> grader["Deterministic grader"]
  grader --> evidence
  bench["Benchmark runner<br/>replay · release gates"] --> worker
  bench --> grader
  bench --> manifests[["Checksummed manifests"]]
```

### A governed tool call

```mermaid
sequenceDiagram
  autonumber
  participant W as Worker
  participant G as Tool gateway
  participant DB as PostgreSQL
  participant T as Tool
  participant O as Operator
  W->>G: Request tool with typed arguments
  G->>G: Validate arguments and scope to the incident
  G->>DB: Commit span, policy decision and audit event
  alt Read-only and in scope
    G->>T: Dispatch with a deadline
    T-->>G: Observation
    G->>DB: Record outcome (unknown completion is never success)
  else Sensitive action
    G->>DB: Create an action-scoped approval and pause the run
    O->>DB: Approve or reject before it expires
  else Unknown or out of scope
    G-->>W: Denied, nothing executed
  end
```

### From scenario to release gate

```mermaid
flowchart LR
  scenario["Versioned scenario<br/>B01 · F01 · F02 · S02 · S03"] --> run["Real run<br/>worker + gateway"]
  run --> evidence["Recorded evidence<br/>checkpoint · spans · decisions · audits"]
  evidence --> grader["Grader v1<br/>4 × 25-point criteria"]
  grader --> gate{"Safety gate"}
  gate -- "violation" --> failed["Failed"]
  gate -- "clean" --> verdict["Passed · Failed · Inconclusive"]
  verdict --> manifest["Benchmark manifest<br/>outcome signature"]
  manifest --> compare["Replay and compare<br/>regressions · release gates"]
```

| Module | Path |
|---|---|
| Agent registry, runs, approvals, traces, overview | `backend/app/api/v1`, `backend/app/services` |
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

Each evaluation has four 25-point criteria — diagnosis, evidence and tool use, policy compliance,
execution reliability — built from explicit checks that cite the spans and decisions they used. A
diagnosis only earns credit if the stored summary can be rebuilt byte-for-byte from the recorded
evidence. Results carry an evidence fingerprint, so regrading the same run reproduces the same
score. Full rules: [docs/evaluation-benchmarks.md](docs/evaluation-benchmarks.md) §20–21.

```bash
uv run python scripts/run_benchmark.py --ensure-agent "Reference Agent"
uv run python scripts/run_benchmark.py --replay <benchmark_run_id>
```

All figures come from a local deterministic simulator; they are engineering checks, not a claim
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

Generate an operator token (keep the token; put only its digest in `.env`):

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

1. **Overview** → unlock operator mode once; the live governance stream and KPIs light up, and
   every other view reuses the session.
2. **Agent registry** → register an agent; it joins the constellation.
3. **Runs and traces** → investigate `INC-1042`; the worker completes it with a diagnosis. Open the
   trace explorer to see every tool span and governance event.
4. **Evaluations** → grade the run against `B01` and open the report. Grade a safe-stop run against
   the same scenario and compare: the regression and its missing evidence are highlighted.
5. **Benchmarks** → run the suite, then **Replay**; the comparison confirms every scenario
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

Operator-only data (traces, approvals, evaluations, benchmarks, overview) requires a bearer token
verified against a server-side SHA-256 digest. Production mode refuses to start without it, hides
the interactive API docs and only allows an explicit HTTPS CORS allowlist. Agent registration and
run submission are currently unauthenticated, which is fine for local use but must change before
any shared deployment. See [docs/security-review.md](docs/security-review.md).

## Stack

Python 3.12 · FastAPI · Pydantic · SQLAlchemy 2 · PostgreSQL · Alembic · React 19 · TypeScript ·
Vite · Three.js · Docker · GitHub Actions

## License

Apache-2.0
