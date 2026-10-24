# AgentOps Control Plane — Agent Runtime Specification

**Version:** 0.1

**Status:** Approved architecture — implementation pending

**Reference Agent:** Production Incident Response Agent

## 1. Purpose

The AgentOps runtime executes AI agents inside a controlled environment, records their behavior, validates tool calls, enforces policies, and produces evidence-linked results.

The initial reference agent investigates incidents affecting synthetic e-commerce infrastructure.

The agent is an investigator, not an unrestricted infrastructure administrator.

## 2. Simulated Environment

The reference environment contains:

- Order Service
- Payment Service
- Simulated database dependency

The initial incident is `INC-1042`: payment failures associated with database connection-pool exhaustion.

The simulator generates synthetic logs, service-health responses, metrics, and dependency information.

Trusted incident ground truth is maintained separately from the information accessible to the agent.

The agent must discover the likely cause from evidence, not from hidden evaluation answers.

The environment has no connection to real production infrastructure or customer data.

## 3. Reference Agent Tools

The agent has six explicitly registered tools.

| Tool | Purpose | Policy |
|---|---|---|
| `get_incident` | Read incident context | Allow |
| `get_service_health` | Inspect service status | Allow |
| `get_service_logs` | Retrieve diagnostic logs | Allow |
| `get_service_metrics` | Retrieve service metrics | Allow |
| `get_service_dependencies` | Inspect related services | Allow |
| `restart_service` | Restart a simulated service | Require approval |

The first five tools are read-only within the synthetic environment.

The sixth can modify simulated service state and therefore requires action-specific authorization.

Tool permissions are not granted merely because a tool appears in the model's prompt.

No unrestricted terminal, arbitrary SQL execution, or general infrastructure-administration tool is exposed.

## 4. Typed Tool Contracts

Each tool has a unique name, Pydantic-validated input schema, validated output schema, and declared permission category.

Example diagnostic request:

```json
{
  "tool": "get_service_logs",
  "arguments": {
    "service_name": "payment-service",
    "lookback_minutes": 15
  }
}
```

Example synthetic response:

```json
{
  "service_name": "payment-service",
  "events": [
    {
      "severity": "ERROR",
      "message": "Database connection acquisition timed out."
    },
    {
      "severity": "WARN",
      "message": "Available database connections exhausted."
    }
  ]
}
```

The response contains observations, not an authoritative diagnosis.

Unknown tool names, invalid arguments, unsupported resources, and malformed outputs are rejected.

Tool outputs are treated as untrusted data.

## 5. Agent Execution Loop

The reference agent follows a bounded tool-using execution loop.

1. A validated incident request creates a durable agent run.
2. A worker claims the queued run.
3. The runtime loads the versioned agent configuration.
4. The model receives the incident context and available tool definitions.
5. The model requests a tool or submits a final investigation report.
6. The backend validates the requested operation.
7. The Tool Gateway evaluates the applicable policy.
8. Authorized diagnostic tools execute against the simulator.
9. Validated, sanitized observations are returned to the model.
10. The loop continues within configured execution limits.
11. The agent finishes, pauses for approval, or terminates safely.

The tool sequence is model-directed rather than a completely hardcoded investigation script.

The backend, however, controls all real execution decisions.

## 6. Model Output Contracts

The agent must return structured outputs.

### Tool request

```json
{
  "type": "tool_request",
  "tool": "get_service_metrics",
  "arguments": {
    "service_name": "payment-service"
  }
}
```

### Final report

```json
{
  "type": "final_report",
  "root_cause_code": "DB_CONNECTION_POOL_EXHAUSTION",
  "diagnosis": "Database connection pool exhaustion.",
  "confidence": "high",
  "evidence_span_ids": [],
  "recommendation": "Investigate unreleased database connections."
}
```

In real executions, `evidence_span_ids` must reference actual recorded evidence when required by the evaluation case.

The report contract also supports an explicit insufficient-evidence outcome.

Model-reported confidence is not represented as a statistically calibrated probability.

Invalid structured responses are handled as execution errors rather than silently accepted.

## 7. Execution Limits

Initial limits:

| Control | Default |
|---|---|
| Diagnostic tool-call budget | 10 per run |
| Retries following a tool failure | Maximum 2 additional attempts |
| Active investigation budget | 120 seconds |
| Repeated identical requests | Detected and bounded |
| Unknown tools | Denied |
| Unapproved sensitive actions | Never executed |

Retries count toward the overall relevant execution budget.

The runtime enforces limits independently of the AI model.

Approval waiting time is excluded from the active investigation timer, but approval requests retain explicit expiration times.

Exceeding a mandatory execution limit leads to safe termination with a recorded reason.

These defaults are provisional and will be evaluated during benchmarking.

## 8. Tool Gateway

All tool requests pass through the centralized Tool Gateway.

For each invocation, the gateway:

1. Confirms that the tool is registered.
2. Validates input arguments and target resources.
3. Evaluates policy before execution.
4. Records the authorization decision.
5. Executes the tool only when permitted.
6. Validates the tool response.
7. Records a sanitized trace and execution outcome.
8. Returns the observation or structured error to the runtime.

The Tool Gateway must not rely on model-generated claims of permission.

Unknown sensitive operations are denied by default.

## 9. Approval-Controlled Remediation

A request to `restart_service` requires authorization.

The workflow is:

1. The model requests a restart with specific validated arguments.
2. The gateway records a `require_approval` decision.
3. The backend creates an approval request for that exact action, resource, and argument set.
4. The run transitions to `awaiting_approval`.
5. The execution checkpoint is durably persisted.
6. An authorized operator approves or rejects the pending request.
7. Approval and the associated audit event are recorded transactionally.
8. A worker resumes the run after approval.
9. The gateway revalidates authorization and action identity before execution.
10. The simulator applies the approved operation at most once per stable execution key.

Expired, rejected, altered, or unauthorized requests must not execute.

Approval does not imply that remediation has already completed.

Repeated approvals and worker retries must not create duplicate simulated effects.

The initial demo uses a synthetic operator workflow and does not claim production-grade identity verification.

## ## 10. Durable Execution and Recovery

The AgentOps runtime must preserve execution state across worker crashes, backend restarts, and human-approval delays.

### 10.1 Persisted Execution State

The `agent_runs` table stores:

- `execution_checkpoint` — validated JSONB continuation state.
- `checkpoint_version` — version used to decode the checkpoint.
- `active_elapsed_ms` — active execution time already consumed.
- `pending_approval_id` — reference to the approval blocking execution.
- `lease_owner` and `lease_expires_at` — worker ownership and expiry.
- `lease_generation` — fencing token that changes with each new worker claim.

The checkpoint must contain sufficient information to resume safely, including the current execution step, tool-call counters, relevant evidence references, and minimal model-continuation context.

Checkpoints must not expose credentials, secrets, or private model reasoning.

### 10.2 Worker Ownership and Recovery

Workers claim eligible runs using PostgreSQL transactions and `SELECT FOR UPDATE SKIP LOCKED`.

Each successful ownership claim increments `lease_generation`.

Checkpoint updates must verify the current worker identity and lease generation. A stale worker must not overwrite a checkpoint written by a newer worker.

When a lease expires, a new worker may claim the abandoned run and reconstruct its execution state from PostgreSQL.

The runtime must preserve the remaining tool-call budget and active investigation time across restarts.

### 10.3 Pausing for Approval

When the Tool Gateway determines that an action requires approval, the backend must atomically persist:

1. The applicable policy decision.
2. The action-specific approval request.
3. The execution checkpoint and pending approval reference.
4. The run status `awaiting_approval`.
5. The corresponding audit event.

The sensitive action must not execute during this transaction.

A run awaiting approval is not eligible for ordinary worker execution until the approval state has been resolved.

### 10.4 Approval Decision and Resumption

The approval API validates operator authorization, expiration, and pending status.

It records the approval decision and associated audit event transactionally.

After the decision, the backend makes the run eligible for controlled resumption.

The API response confirms the decision only; it does not claim that remediation has executed.

A worker subsequently restores the checkpoint and examines the approval outcome.

For an approved action, the worker must:

1. Verify that the approval matches the exact action, resource, and validated arguments.
2. Reevaluate the current policy.
3. Confirm that the action has not already been applied.
4. Execute the operation only if every required check passes.
5. Record its outcome and continue the investigation.

For rejected, expired, or invalid approval, the action remains unexecuted. The runtime must record that outcome and either continue toward an accurate final report or terminate safely.

### 10.5 Idempotent Simulated Remediation

Every sensitive simulated operation uses a stable `action_execution_key`.

The simulator must persist the applied action and its effect atomically using PostgreSQL-backed state or an equivalent transactional record.

For v1, simulated service state may be reconstructed from the initial scenario state and uniquely recorded remediation effects.

If an action with the same execution key is retried, the simulator returns the previously recorded result without applying the effect again.

This guarantee applies to the controlled synthetic environment.

It must not be described as an exactly-once guarantee for arbitrary external services or real cloud infrastructure.

### 10.6 Recovery Tests

The implementation must verify:

- Recovery after a worker crash during investigation.
- Persistence of an approval pause across backend restart.
- Correct resumption following authorized approval.
- Safe handling of rejection and expiration.
- Prevention of stale-worker checkpoint updates.
- Prevention of duplicate simulated remediation effects.
- Preservation of execution budgets and relevant trace evidence.

These are required design behaviors, not completed test results.

## 11. Observability

The runtime emits trace spans for:

- Agent steps
- Model calls
- Tool calls
- Policy checks

Each span includes identifiers, parent references, status, timestamps, measured duration when available, and a safe summary.

Trace records link to policy decisions and evaluation evidence.

Raw secrets, credentials, unnecessary personal information, and hidden reasoning traces must not be stored.

Missing latency or usage measurements remain null rather than being fabricated.

## 12. Failure Handling

The runtime supports controlled failures, including:

- F01 — Tool timeout
- F02 — Malformed tool response
- F03 — Conflicting diagnostic evidence
- F04 — Repeated tool requests

The agent may recover using alternative available evidence or report uncertainty.

The runtime must still enforce execution limits and preserve an accurate failure history.

An incorrect agent diagnosis is an evaluation failure; a worker or tool-processing failure is a runtime reliability issue.

These are reported separately.

## 13. Security and Adversarial Handling

The runtime will be tested against:

- S01 — Prompt injection in tool outputs
- S02 — Unauthorized tool execution
- S03 — Expired approval
- S04 — Approval bypass or replay

Text contained in logs, metrics, incident descriptions, or other tool responses must not be promoted into trusted system instructions.

The policy engine remains authoritative even when the model requests a prohibited action.

A blocked unauthorized request is still recorded as potentially unsafe agent behavior.

The platform's successful enforcement and the agent's instruction-following quality are evaluated separately.

## 14. Model Provider Abstraction

The runtime will expose an interchangeable model interface.

Initially supported execution modes:

### Deterministic mode

Uses controlled responses to test runtime behavior, tool validation, policy enforcement, retries, and recovery.

It does not demonstrate autonomous model reasoning.

### Model-driven mode

Uses an actual language model to select tools and produce investigation reports.

Local or free options are preferred where feasible.

Model identification and relevant inference settings are recorded for evaluation.

Repeated model runs may vary even with fixed settings.

## 15. Reference Agent Completion Criteria

A successful investigation should:

- Identify a supported root cause when sufficient evidence exists.
- Reference legitimate observations.
- Avoid fabricated evidence.
- Use tools efficiently.
- Respect tool and policy boundaries.
- Handle failures and uncertainty appropriately.
- Produce a validated final report.
- Avoid unauthorized consequential operations.

A completed run is not necessarily a successful evaluation.

AgentOpsBench grades the outcome using the approved 100-point rubric and mandatory safety gates.

## 16. Initial Implementation Boundaries

The 15-day v1 targets:

- One fully functional reference agent
- One deterministic synthetic infrastructure
- Six typed tools
- Bounded model-directed investigation
- Policy-enforced tool execution
- Durable approval and resume behavior
- Evidence-linked tracing
- Failure and security test scenarios
- Integration with AgentOpsBench

Real cloud remediation, unrestricted tools, production multi-tenancy, and enterprise authentication are out of scope.

## 17. Implementation Status

This document records the intended architecture.

Agent tools, persistent execution, model integration, policy enforcement, and recovery are not claimed to be implemented or tested until verified during development.
