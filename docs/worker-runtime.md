# AgentOps Control Plane — Worker Runtime

## Overview

The Day 8 worker provides database-backed execution of deterministic,
read-only incident investigations.

It coordinates PostgreSQL job claiming, diagnostic tool execution,
checkpoint persistence, lease renewal, recovery, and finalization.

The current reference scenario is INC-1042.

## Execution flow

1. A run is created in the queued state.
2. A worker atomically claims an eligible run.
3. PostgreSQL records the worker identity, lease, and fencing generation.
4. The worker restores any previously persisted investigation checkpoint.
5. It renews its lease before each diagnostic step.
6. It executes the next read-only diagnostic tool.
7. It persists evidence or failure accounting after each attempt.
8. It produces an evidence-based investigation report.
9. It finalizes the run as completed or failed.

## Reliability guarantees

### Atomic claiming

Workers use PostgreSQL row locking with SKIP LOCKED to prevent
simultaneous claims of the same eligible run.

### Fencing

Checkpoint writes, lease renewal, and finalization require a valid
worker identity, fencing generation, and unexpired lease.

A stale worker cannot persist progress or finalize a run after
another worker has reclaimed it.

### Recovery

Investigation checkpoints include the next step, completed evidence,
failed attempts, and diagnostic-call consumption.

After lease expiration, a replacement worker can restore the saved
checkpoint and resume from the next unfinished step.

### Execution limits

- Maximum diagnostic calls: 10
- Maximum additional retries per diagnostic step: 2
- Active execution budget: 120 seconds
- Default individual diagnostic timeout: 15 seconds
- Lease renewal duration: 180 seconds

The active execution budget is accumulated across worker recovery.

### Finalization

Successful investigations are finalized as completed with a
human-readable result summary.

Unsupported execution modes, retry exhaustion, execution-budget
violations, and diagnostic timeouts are recorded as failed runs.

Finalization is fenced and cannot be repeated after completion.

## Safety boundaries

The deterministic worker currently uses simulated, read-only tools.

Service restart and other state-changing operations are not enabled.
They will require a separately enforced Tool Gateway, authorization
policies, and explicit approval workflows.

The current timeout implementation bounds how long the async worker
waits for a diagnostic call. It does not forcibly terminate an
underlying Python thread. Production tool adapters will require
provider-level timeouts, cancellation controls, and careful
side-effect handling.

Lease renewal occurs between diagnostic steps, not continuously
during a blocked diagnostic call.

The runtime is currently deterministic. Autonomous model-directed
tool selection and production-grade worker supervision remain future
work.

## Testing

The backend suite covers:

- Atomic and concurrent claiming
- Lease expiration and recovery
- Stale-worker fencing
- Durable checkpoints
- Successful and failed finalization
- Deterministic incident investigation
- Evidence-based reporting
- Retry and diagnostic-call budgets
- Interrupted-investigation recovery
- Lease renewal
- Diagnostic timeout behavior

PostgreSQL integration tests must run only against the isolated
agentops_test database with AGENTOPS_RUN_DB_INTEGRATION=1.

The development database must not be used for integration tests.
