# AgentOps Control Plane — Database Design

**Version:** 0.1

**Status:** Proposed implementation specification

**Database:** PostgreSQL 17

## 1. Design Principles

AgentOps uses PostgreSQL as the system of record for agent execution, observability, evaluations, policy enforcement, approvals, and auditing.

The initial database contains nine core tables.

All primary keys use UUIDs. Timestamps use timezone-aware UTC values. JSONB is reserved for flexible structured metadata, not as a replacement for important relational fields.

## 2. Core Tables

### 2.1 agents

Stores registered AI agents.

Key fields:
- id — UUID primary key
- name — required, maximum 80 characters
- description — optional, maximum 500 characters
- agent_type — initially `incident_response`
- status — active or disabled
- config_version — positive integer
- config_json — validated agent settings
- created_at, updated_at

Agent configuration used in each run must be snapshotted to preserve historical reproducibility.

### 2.2 agent_runs

Stores agent executions and acts as the durable initial job queue.

Key fields:
- id — UUID primary key
- agent_id — foreign key to agents
- incident_id — synthetic incident identifier
- status — queued, running, awaiting_approval, completed, failed, or cancelled
- agent_config_version
- agent_config_snapshot — JSONB
- execution_mode — deterministic or model
- idempotency_key — nullable
- request_fingerprint — nullable
- attempt_count — non-negative integer
- lease_owner — nullable worker identifier
- lease_expires_at — nullable timestamp
- lease_generation — integer used to fence stale workers
- execution_checkpoint — nullable, validated JSONB continuation state
- checkpoint_version — version of the checkpoint structure
- active_elapsed_ms — accumulated active execution time
- pending_approval_id — nullable reference to the blocking approval request
- created_at, started_at, finished_at
- result_summary, error_code
- benchmark_run_id — nullable UUID for benchmark grouping

#### Idempotency

Non-null idempotency keys must be unique within the defined agent/run-creation operation scope.

An identical request using the same key returns the existing run. Reusing the key with a different request fingerprint produces a conflict.

Concurrent duplicate submissions must be resolved atomically through PostgreSQL constraints and transactions.

#### Durable execution checkpoints

The execution checkpoint preserves sufficient validated state to resume an interrupted investigation.

It includes the current execution position, bounded tool-use counters, relevant evidence references, and necessary model continuation context.

Sensitive information must be minimized and protected. Checkpoints are internal state and must not be returned in public API responses.

The active execution-time budget is preserved across worker restarts. Time spent waiting for approval is excluded from the active investigation budget.

#### Worker claiming and recovery

Workers claim eligible jobs using PostgreSQL transactions and SELECT FOR UPDATE SKIP LOCKED.

Each new ownership claim advances lease_generation. Checkpoint updates must verify the current lease owner and generation so stale workers cannot overwrite newer execution state.

Expired worker leases permit controlled recovery.

Recovery reconstructs execution from persisted state and checks whether consequential simulated actions have already been applied.

#### Approval consistency

When execution pauses for approval, the checkpoint, pending approval reference, relevant policy decision, and awaiting_approval run state must be committed consistently.

The worker must not execute the sensitive action until the required approval is valid and current policy checks pass.

Stable action execution keys and atomic simulated-effect recording prevent duplicate simulated remediation effects.

These guarantees apply to the controlled simulator, not arbitrary external infrastructure.


### 2.3 trace_spans

Stores sanitized execution evidence.

Key fields:
- id — UUID primary key
- run_id — foreign key to agent_runs
- parent_span_id — nullable self-reference
- span_type — agent_step, tool_call, model_call, or policy_check
- name, status
- started_at, ended_at
- duration_ms — nullable, measured value
- safe_summary
- sanitized_attributes — JSONB

The application verifies that a child span belongs to the same run as its parent.

Sensitive values are redacted before persistence.

### 2.4 evaluation_cases

Stores versioned benchmark and evaluation definitions.

Key fields:
- id — UUID primary key
- scenario_key — stable identifier
- version — positive integer
- category — baseline, operational_failure, security, or integration
- scenario_config — JSONB
- expected_outcome — restricted JSONB
- grader_config — JSONB
- created_at
- allowed_terminal_statuses — validated non-empty set of permitted terminal run states (`completed`, `failed`, `cancelled`), defined by the trusted evaluation case; defaults to `completed` for standard diagnosis cases.

Each scenario-key/version combination must be unique.

Ground-truth answers and grader expectations must not be passed into agent prompts or diagnostic tool responses.

### 2.5 evaluation_results

Stores evaluation jobs and outcomes.

Key fields:
- id — UUID primary key
- run_id — foreign key to agent_runs
- evaluation_case_id — foreign key to evaluation_cases
- case_version, grader_version
- status — queued, running, completed, or failed
- verdict — passed, failed, inconclusive, or null
- score — nullable, between 0 and 100
- passing_threshold
- policy_gate_passed — nullable boolean
- criteria_results — JSONB
- evidence_span_ids — validated references
- idempotency_key — nullable
- request_fingerprint — nullable
- lease_owner, lease_expires_at, attempt_count
- created_at, finished_at

Completed evaluation results are treated as append-only. Regrading creates a new result rather than overwriting historical evidence.

A failed grading job is distinct from an agent that received a failing evaluation verdict.

### 2.6 policy_rules

Stores versioned authorization rules.

Key fields:
- id — UUID primary key
- rule_key, version
- action_pattern, resource_pattern
- effect — allow, require_approval, or deny
- priority
- rule_config — JSONB
- enabled
- created_at

Rule definitions used for historical decisions must remain identifiable by version.

Unknown or unmatched sensitive actions are denied by default.

### 2.7 policy_decisions

Stores individual authorization decisions.

Key fields:
- id — UUID primary key
- run_id — foreign key to agent_runs
- trace_span_id — nullable reference
- policy_rule_id — nullable reference
- policy_rule_version — nullable
- action, resource
- decision — allow, require_approval, or deny
- reason_code, reason
- executed — boolean
- created_at

Policy enforcement happens in the backend Tool Gateway, not in model-generated text or frontend code.

### 2.8 approval_requests

Stores approval-controlled actions.

Key fields:
- id — UUID primary key
- run_id — foreign key to agent_runs
- policy_decision_id — foreign key to policy_decisions
- action, resource
- validated_action_arguments — JSONB
- action_execution_key — unique identifier
- risk_level, reason
- status — pending, approved, rejected, or expired
- execution_status — not_started, pending_execution, executed, skipped, or failed
- decision_reason
- decision_idempotency_key — nullable
- decided_by — nullable
- requested_at, expires_at, decided_at, executed_at

Approvals are specific to one validated action, resource, and argument set.

A database transaction must protect concurrent approval decisions. The worker rechecks authorization before executing an approved action.

The simulator must recognize execution keys to avoid repeating consequences after a retry. Database transactions alone cannot guarantee exactly-once effects in external systems.

The initial local demonstration uses a simulated operator; it must not be represented as enterprise-grade authentication.

### 2.9 audit_events

Stores important operational and security events.

Key fields:
- id — UUID primary key
- run_id — nullable foreign key to agent_runs
- actor_type, actor_identifier
- event_type
- resource_type, resource_id
- event_payload — sanitized JSONB
- created_at

Examples:
- Agent registered
- Run started
- Policy denied action
- Approval requested
- Approval granted or rejected
- Simulated remediation executed
- Evaluation completed

Audit events are append-only through the application interface. This does not by itself make them cryptographically tamper-proof.

## 3. Relationships

- One agent can have many agent runs.
- One agent run can have many trace spans.
- One agent run can have many evaluation results.
- One evaluation case can have many evaluation results.
- One policy rule can have many recorded policy decisions.
- One agent run can have many policy decisions and audit events.
- One approval request references the policy decision that triggered it.
- Trace spans may form a parent-child hierarchy.

## 4. Constraints and Indexes

Required indexes include:
- Agent runs by agent_id, status, and created_at
- Queued agent runs by status and lease expiration
- Trace spans by run_id and started_at
- Evaluation results by run_id, case, and status
- Policy decisions by run_id and created_at
- Pending approvals by status and expires_at
- Audit events by run_id and created_at

Use database constraints for valid statuses, score ranges, required keys, and important uniqueness rules.

Foreign keys must prevent invalid references without unnecessarily deleting historical audit records.

## 5. Durability and Recovery

Queued jobs are stored in PostgreSQL.

Workers claim jobs transactionally and use leases to detect abandoned work.

Approval waits must survive backend restarts. Resumption uses persisted run and action state rather than only in-memory state.

All consequential operations require stable execution keys and explicit recovery rules.

## 6. Benchmark Persistence

AgentOpsBench v1 uses versioned JSON manifests and recorded run/evaluation IDs.

The manifest includes:
- benchmark_run_id
- suite version and scenario versions
- simulator version and seed
- agent and model configuration
- grader version
- Git commit SHA
- execution mode
- participating run IDs and evaluation IDs

Generated JSON and Markdown reports reference these underlying records.

The benchmark result is not considered complete until required outcomes and evidence have been durably recorded.

A separate benchmark_runs database table may be introduced later if reporting and concurrency require it.

## 7. Security and Privacy

Never store API keys, raw secrets, or sensitive credentials in trace attributes.

Protect evaluation ground truth from the agent runtime.

Use server-side authorization for approval actions in any deployment that supports real users.

Use transactions for approval decisions and related audit writes.

## 8. Implementation Status

This document specifies the intended schema. No database migrations or production persistence behaviors are claimed to exist yet.

The final SQL schema and migration tests must validate these constraints before implementation is considered complete.
