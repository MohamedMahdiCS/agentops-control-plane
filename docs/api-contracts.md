# AgentOps Control Plane — API Contracts

**Version:** 0.1

**Status:** Approved core design — implementation pending

**Framework:** FastAPI with Pydantic

**Base path:** `/api/v1`

## 1. API Design Principles

AgentOps exposes a versioned REST API for managing agents, running investigations, inspecting traces, evaluating performance, and enforcing approval workflows.

All API contracts follow these principles:

- JSON request and response bodies.
- UUID identifiers for database-backed resources.
- ISO 8601 UTC timestamps.
- Pydantic validation for all inputs and outputs.
- Consistent structured errors.
- Cursor-based pagination for growing collections.
- Idempotency for consequential or asynchronous operations.
- No credentials or sensitive internal details in API responses.
- API execution must not bypass backend policy enforcement.

The initial application is a controlled local demonstration. Production deployment requires authenticated identities and authorization controls.

## 2. Core API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Check backend health |
| GET | `/agents` | List registered agents |
| POST | `/agents` | Register an agent |
| POST | `/agents/{agent_id}/runs` | Start an incident investigation |
| GET | `/runs/{run_id}` | Retrieve execution state |
| GET | `/runs/{run_id}/traces` | Retrieve execution spans |
| POST | `/runs/{run_id}/evaluations` | Queue an evaluation |
| GET | `/runs/{run_id}/evaluations` | Retrieve evaluation results |
| GET | `/runs/{run_id}/policy-decisions` | Inspect authorization decisions |
| GET | `/approvals` | List approval requests |
| POST | `/approvals/{approval_id}/decision` | Approve or reject an action |
| GET | `/overview` | Retrieve dashboard aggregates |

All paths above are relative to `/api/v1`.

## 3. Health

### GET `/api/v1/health`

Returns the service's basic readiness information.

Example:

```json
{
  "status": "ok",
  "service": "agentops-api",
  "version": "0.1.0"
}
```

A successful application response uses HTTP 200.

Dependency failures must be reported accurately rather than presenting an unhealthy service as ready.

## 4. Agent Registration

### POST `/api/v1/agents`

Request:

```json
{
  "name": "Production Incident Agent",
  "description": "Investigates simulated service incidents.",
  "agent_type": "incident_response"
}
```

Validation:
- Name: 1–80 characters.
- Description: optional, maximum 500 characters.
- Agent type: initially `incident_response`.

Successful response: HTTP 201.

```json
{
  "id": "69ae4c8e-2c60-42c3-9b6f-a5b99438a003",
  "name": "Production Incident Agent",
  "agent_type": "incident_response",
  "status": "active",
  "config_version": 1,
  "created_at": "2026-10-24T06:00:00Z"
}
```

The backend generates identifiers and timestamps. The client cannot choose its own configuration version.

### GET `/api/v1/agents`

Returns a paginated collection of agent summaries.

Supports `limit` and `cursor`.

## 5. Create an Agent Run

### POST `/api/v1/agents/{agent_id}/runs`

Request:

```json
{
  "incident_id": "INC-1042"
}
```

Optional header:

`Idempotency-Key: <unique-request-key>`

Successful response: HTTP 202 Accepted.

```json
{
  "run_id": "a871202d-024a-4307-bd6b-627b19723113",
  "agent_id": "69ae4c8e-2c60-42c3-9b6f-a5b99438a003",
  "incident_id": "INC-1042",
  "status": "queued",
  "created_at": "2026-10-24T06:01:00Z"
}
```

The response includes a `Location` header pointing to the run resource.

The backend must:
1. Verify that the agent exists and can run.
2. Validate the incident identifier.
3. Persist the run before acknowledging it.
4. Queue execution durably.
5. Protect retries using idempotency.

Repeating the same valid idempotent request returns the existing run. Reusing the same key within its defined scope for a different request returns HTTP 409.

## 6. Retrieve Agent Run

### GET `/api/v1/runs/{run_id}`

Response fields:
- run_id
- agent_id
- agent_config_version
- incident_id
- status
- created_at
- started_at
- finished_at
- result_summary
- error

Run states:

`queued`, `running`, `awaiting_approval`, `completed`, `failed`, `cancelled`.

Timestamps and output fields may be null until relevant work has occurred.

A completed run does not automatically mean it passed evaluation.

The frontend can poll active runs approximately every 2–3 seconds, pausing polling when appropriate.

## 7. Execution Traces

### GET `/api/v1/runs/{run_id}/traces`

Query parameters:
- `limit` — default 50, with a validated upper bound.
- `cursor` — opaque continuation cursor.

Response structure:

```json
{
  "run_id": "a871202d-024a-4307-bd6b-627b19723113",
  "spans": [
    {
      "id": "221d1ce8-6b99-4d3c-af29-314e8e2052a0",
      "parent_span_id": null,
      "type": "tool_call",
      "name": "get_service_logs",
      "status": "completed",
      "started_at": "2026-10-24T06:01:02Z",
      "ended_at": "2026-10-24T06:01:03Z",
      "duration_ms": 420,
      "safe_summary": "Retrieved synthetic payment-service logs."
    }
  ],
  "next_cursor": null
}
```

Span types:
- `agent_step`
- `tool_call`
- `model_call`
- `policy_check`

All returned details must be sanitized.

Trace identifiers support deep links from evaluation findings and security decisions.

Only measured durations may be reported. Missing measurements must remain null.


## 8. Evaluations (implemented, Day 12)

All evaluation routes require an authenticated operator (`Authorization: Bearer`). Authentication runs before any database access. The client never supplies grader weights, thresholds, expected answers or allowed terminal states; these come from the versioned server-side scenario catalog.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/evaluations/cases` | List published scenario versions |
| POST | `/api/v1/evaluations/cases/sync` | Publish missing scenario versions; verify existing ones are unchanged |
| POST | `/api/v1/evaluations` | Grade a run against a scenario and append the result |
| GET | `/api/v1/evaluations` | History, newest first (`run_id`, `scenario_key`, `verdict`, `limit` ≤ 100) |
| GET | `/api/v1/evaluations/{evaluation_id}` | Full report with criteria, checks and evidence references |
| GET | `/api/v1/evaluations/overview` | Aggregates computed from stored results only |
| GET | `/api/v1/evaluations/compare?baseline_id=&candidate_id=` | Regression comparison |

### 8.1 Create an Evaluation

`POST /api/v1/evaluations`

```json
{ "run_id": "…", "scenario_key": "B01", "scenario_version": 1 }
```

`scenario_version` is optional and defaults to the latest published version. An optional `Idempotency-Key` header (8–128 characters) makes retries safe: an identical retry returns the stored result with HTTP 200; reusing the key for a different request returns HTTP 409.

Responses:

- `201 Created` with the full evaluation report and a `Location` header.
- `404` unknown run or scenario.
- `409` run not in a terminal state (`queued`, `running`, `awaiting_approval`), scenario not applicable to the run (different incident or execution mode), idempotency conflict, or a stored scenario version that differs from the published definition.

Deviation from the original plan: grading is deterministic and completes within the request, so results are stored directly with job status `completed` rather than queued asynchronously. The path is `/api/v1/evaluations` with `run_id` in the body or query instead of `/api/v1/runs/{run_id}/evaluations`.

### 8.2 Evaluation Independence

Agent run status, evaluation job status, and evaluation verdict are distinct. A completed run does not automatically pass, and a failed run does not automatically fail: a safe stop passes when the scenario explicitly expects it (for example `F02`, retry exhaustion).

### 8.3 Results and History

Each result includes the scenario and grader versions, verdict (`passed`, `failed`, `inconclusive`), 0–100 score, passing threshold, safety-gate result, per-criterion checks with evidence references, linked trace-span IDs, and an evidence fingerprint. Regrading appends a new record; completed results are never modified. Re-grading identical evidence reproduces the same fingerprint and score.

The comparison endpoint only compares results with the same scenario key, scenario version and grader version (otherwise HTTP 422) and reports verdict change, score delta, per-criterion deltas, per-check status changes, new or resolved safety violations, and a `regression` flag.

See `docs/evaluation-benchmarks.md` §20 for the grading rules.

### 8.4 Benchmarks (implemented, Day 13)

All routes require an authenticated operator.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/benchmarks` | Benchmark summaries (newest first) and identifiers of manifests that failed integrity checks |
| POST | `/api/v1/benchmarks` | Run the suite: `{"agent_id": "…", "scenario_keys": ["B01"], "label": "…"}` (keys and label optional) → 201 |
| GET | `/api/v1/benchmarks/{id}` | Manifest plus measured performance summary |
| POST | `/api/v1/benchmarks/{id}/replay` | Re-execute the same scenario versions as a new benchmark → 201 |
| POST | `/api/v1/benchmarks/{id}/resume` | Continue an interrupted benchmark without duplicating completed work |
| GET | `/api/v1/benchmarks/{id}/compare?baseline_id=` | Regression and reproducibility comparison (422 if incompatible) |
| GET | `/api/v1/benchmarks/{id}/report.md` | Markdown report, optionally with `baseline_id` |

Errors: 404 unknown benchmark, 409 another benchmark running or manifest failed integrity validation, 422 invalid configuration (unknown scenario, disabled agent).

## 10. Policy Decisions

### GET `/api/v1/runs/{run_id}/policy-decisions`

Returns recorded policy checks.

Each decision includes:
- decision ID
- action
- resource
- policy rule ID and version
- decision: `allow`, `require_approval`, or `deny`
- reason code
- human-readable reason
- linked approval ID, when applicable
- executed flag
- timestamp

Policy decisions are historical records, not client-side authorization instructions.

All tool execution permissions are enforced again at the backend boundary.


## 11. Approval Requests and Operator Authorization

The approval API allows an authorized operator to review and decide whether a sensitive simulated action may proceed.

Approval authorization is enforced by FastAPI, independently of the React frontend and AI agent.

### 11.1 Local Operator Authentication

For v1, AgentOps uses a locally configured operator credential.

Requirements:

- Generate a strong random credential and supply it through a server-side environment variable.
- Never hardcode credentials in source code or frontend bundles.
- Require an Authorization: Bearer header for protected approval endpoints.
- Verify credentials on the backend using a constant-time comparison.
- Associate a validated credential with a server-defined demo operator identity.
- Never accept client-supplied operator names as proof of authorization.
- Do not log credentials or expose them in API responses.
- Keep any credential entered into the React interface in session memory, not browser local storage.
- Bind the demonstration backend to localhost by default.
- Restrict browser origins to explicitly configured local development origins.

If the operator credential is not configured, approval operations must fail closed rather than become publicly accessible.

This mechanism is limited to the local demonstration. It is not enterprise authentication.

### 11.2 List Approval Requests

GET `/api/v1/approvals?status=pending`

Requires an authorized operator credential.

Returns a paginated collection containing:

- approval_id
- run_id
- action
- resource
- risk_level
- reason
- requested_at
- expires_at
- status

Supported filters must be validated server-side.

The frontend must not assume that a previously displayed pending approval remains valid.

### 11.3 Record an Approval Decision

POST `/api/v1/approvals/{approval_id}/decision`

Requires an authorized operator credential.

Example request:

```json
{
  "decision": "approve",
  "reason": "Reviewed the diagnostic evidence."
}
```

Supported decisions:

- approve
- reject

An optional Idempotency-Key header supports safe retries.

The backend verifies:

1. The operator credential is valid.
2. The operator is authorized for this demonstration action.
3. The approval exists and is pending.
4. The approval has not expired.
5. The recorded action, resource, and arguments have not been altered.
6. The decision is recorded atomically with its audit event.

A successful response returns HTTP 200 with the recorded approval status and associated run state.

The response must distinguish approval from actual action execution.

Approving an action does not execute it inside the HTTP request.

### 11.4 Safe Execution After Approval

Following approval, a worker resumes the associated run using its durable execution checkpoint.

Before executing any sensitive action, the worker must:

- Verify the approval belongs to the exact requested action.
- Recheck the current policy.
- Verify the action's execution key.
- Check whether the simulated effect was already applied.
- Execute only when all required conditions are satisfied.
- Persist the execution outcome and audit evidence.

Rejection, expiration, or failed revalidation prevents the sensitive action from executing.

### 11.5 Authorization and Conflict Errors

Expected error handling:

- HTTP 401: Missing or invalid operator credential.
- HTTP 403: Authenticated operator lacks required permission, if roles are introduced.
- HTTP 404: Approval request does not exist.
- HTTP 409: Conflicting, expired, or already-decided approval.
- HTTP 422: Invalid request body.
- HTTP 503: Required local authorization configuration unavailable.

Errors must use the standard structured API error format without exposing credentials or internal secrets.

### 11.6 Required Security Tests

The implementation must verify:

- Requests without credentials are rejected.
- Invalid credentials are rejected.
- Missing authorization configuration fails closed.
- Expired approvals cannot be accepted.
- Conflicting decisions cannot overwrite recorded decisions.
- Repeated identical decisions do not create duplicate effects.
- Approved actions are revalidated before execution.
- Operator identity is derived from the server-side authorization context.

These are implementation requirements, not completed security test results.

### 11.7 Scope Limitation

AgentOps v1 permits consequential actions only against controlled synthetic infrastructure.

Enterprise identity management, multiuser roles, SSO, public deployment hardening, and real infrastructure authorization are deferred.

## 12. Overview Dashboard

### GET `/api/v1/overview?window=24h`

Supported windows:
- `24h`
- `7d`
- `30d`

Returns:
- Total runs
- Run success rate
- Evaluation pass rate
- Current pending approval count
- Activity series
- Recent runs
- Items requiring attention

Rates must include clear numerator and denominator definitions.

When a rate cannot be calculated, return null rather than inventing zero or a percentage.

Pending approval count is a current-state measure, while historical activity respects the selected time window.

The frontend may refresh overview data approximately every 15 seconds.

## 13. Standard Error Handling

All errors follow a consistent structured format.

Example:

```json
{
  "error": {
    "code": "RUN_NOT_FOUND",
    "message": "The requested run was not found.",
    "request_id": "req-example-001"
  }
}
```

Expected HTTP statuses:

| Status | Meaning |
|---|---|
| 200 | Successful retrieval or decision |
| 201 | Resource created |
| 202 | Asynchronous operation accepted |
| 400 | Invalid operation or unsupported state |
| 403 | Forbidden action |
| 404 | Resource not found |
| 409 | State or idempotency conflict |
| 422 | Request validation failure |
| 429 | Rate limit exceeded, when enabled |
| 500 | Internal server error |
| 503 | Service temporarily unavailable |

Request validation errors must use the documented public error shape, including FastAPI's default 422 handling where necessary.

Never expose stack traces, credentials, system prompts, or raw database errors to API clients.

## 14. Pagination and Consistency

Growing collections use deterministic sorting with opaque cursors.

Pagination must avoid duplicate or missing items when timestamps are equal.

All identifiers included in nested results must refer to valid, accessible resources.

## 15. Idempotency and Concurrency

Idempotency keys are scoped to the relevant operation and authorized requester where applicable.

The backend must ensure:
- Safe repeated submissions.
- Clear conflict responses when payloads differ.
- Transactionally protected approval state transitions.
- Durable job claiming and recovery.
- Stable simulated action execution identifiers.

A successful HTTP acknowledgement must not falsely imply completion of asynchronous work.

## 16. Identified Endpoint Gaps

The planned Run Details page includes an Audit tab, but the approved core endpoints do not yet include audit-event retrieval.

Proposed additional endpoint:

`GET /api/v1/runs/{run_id}/audit-events`

This should return a paginated, access-controlled, sanitized audit history.

Detailed benchmark-report endpoints are also deferred until AgentOpsBench storage and execution contracts are finalized.

These are explicitly identified design additions, not implemented APIs.

## 17. OpenAPI Documentation

FastAPI should expose a generated OpenAPI specification and local interactive documentation.

Request and response models must provide machine-readable schemas and appropriate examples.

Automated API tests will validate status codes, schemas, error behavior, idempotency, and policy boundaries.

## 18. Implementation Status

This document describes intended behavior.

No endpoint should be described as implemented, secured, tested, or operational until verified through the corresponding implementation and automated tests.
