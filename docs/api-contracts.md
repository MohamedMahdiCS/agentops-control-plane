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


## 8. Create an Evaluation

### POST `/api/v1/runs/{run_id}/evaluations`

Queues an asynchronous evaluation of a recorded agent run.

Request:

```json
{
  "evaluation_case_id": "63d789d6-62ac-45c0-950b-26cded70b4fd"
}
```

Successful response: HTTP 202 Accepted.

Response fields:
- evaluation_result_id
- run_id
- evaluation_case_id
- status: `queued`
- score: null
- verdict: null

### 8.1 Evaluation Eligibility

A run is eligible for evaluation only when it has reached a terminal state supported by the selected evaluation case.

Terminal run states:
- `completed`
- `failed`
- `cancelled`

Eligibility rules:

- Standard diagnosis cases normally require `completed`.
- Failure-handling cases may allow `completed` or `failed`.
- Cancelled runs are eligible only when explicitly supported by the evaluation case.
- Runs in `queued`, `running`, or `awaiting_approval` cannot receive a final evaluation.

The trusted evaluation case defines its allowed terminal states in a versioned server-controlled configuration.

The frontend cannot override these eligibility rules.

An incompatible run or evaluation case returns HTTP 409 Conflict.

Unknown run or case identifiers return HTTP 404.

### 8.2 Evaluation Independence

Agent run status, evaluation job status, and evaluation verdict are distinct.

A completed run does not automatically pass evaluation.

A failed run does not automatically fail evaluation.

Safe termination counts as successful behavior only when the evaluation case explicitly permits it and recorded evidence supports that outcome.

### 8.3 Evaluation Execution

The backend loads trusted evaluation criteria from the stored case.

The client cannot supply:
- Grader weights
- Passing thresholds
- Expected answers
- Allowed terminal states

Evaluation execution is asynchronous, durable, and retry-safe.

The endpoint supports an optional `Idempotency-Key` header.

An identical retry reuses the corresponding evaluation operation. Conflicting use of the same scoped key returns HTTP 409.

The grader records its result separately from the agent execution status.


## 9. Retrieve Evaluation Results

### GET `/api/v1/runs/{run_id}/evaluations`

Returns paginated evaluation results.

Each result includes:
- evaluation_result_id
- evaluation_case_id
- case_version
- grader_version
- status
- verdict
- score
- passing_threshold
- policy_gate_passed
- criteria
- evidence references
- created_at
- finished_at

Evaluation job states:

`queued`, `running`, `completed`, `failed`.

Evaluation verdicts:

`passed`, `failed`, `inconclusive`.

A failed evaluation job is different from a completed evaluation with a failing verdict.

Completed evaluations must preserve their original grading evidence. Regrading creates a new evaluation record.

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
