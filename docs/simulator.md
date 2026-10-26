# Synthetic Incident Simulator

## Purpose

The simulator provides a deterministic environment for testing
AI incident-response agents without connecting to production systems.

It supports evidence collection, tool validation, fault injection,
and controlled testing of sensitive-operation boundaries.

## Reference Incident

Incident: INC-1042

Scenario: Elevated payment failures and delayed order processing.

Service dependency chain:

order-service -> payment-service -> database

The simulator exposes diagnostic evidence for these services,
including health observations, timestamped logs, numerical metrics,
and dependency relationships.

All observations use a fixed scenario clock for reproducibility.

## Tool Registry

Five read-only diagnostic tools are available:

1. get_incident
2. get_service_health
3. get_service_logs
4. get_service_metrics
5. get_service_dependencies

One sensitive tool is defined:

6. restart_service

Tool inputs and outputs use strict Pydantic contracts.

The central registry rejects unknown tools, unsupported resources,
and invalid input arguments.

## Security Boundary

restart_service is intentionally non-executable.

Valid restart requests raise ApprovalRequiredError.

Caller-supplied approval flags are rejected.

A future Tool Gateway will enforce authorization policies,
operator approvals, and controlled remediation execution.

The current simulator does not restart real or synthetic services.

## Fault Injection

FaultInjectingSimulator supports deterministic injection of:

- Tool timeouts
- Rate limits
- Internal tool errors

Faults are configured by tool name and invocation number.

The reset operation supports reproducible test replay.

Fault injection cannot authorize sensitive operations.

## Running Tests

Simulator tests:

    uv run pytest -q tests/test_simulator.py tests/test_simulator_faults.py

Python linting:

    uv run ruff check backend/app/simulator tests/test_simulator.py tests/test_simulator_faults.py

Python formatting:

    uv run ruff format --check backend/app/simulator tests/test_simulator.py tests/test_simulator_faults.py

Database-backed integration tests require explicit activation
and must use the isolated agentops_test database.

## Current Limitations

- The simulator contains one reference incident.
- Evidence is deterministic rather than live telemetry.
- Fault injection is a test harness, not production middleware.
- There is no background agent execution worker yet.
- Sensitive remediation is disabled.
- Operator approvals and policy enforcement are future work.
- Automated agent evaluation and benchmark scoring are future work.

## Planned Integration

The agent worker will consume these tools through a controlled
execution interface.

The future Tool Gateway will enforce centralized authorization
before sensitive tool execution.

Tracing and evaluation components will record tool use,
agent decisions, failures, and benchmark results.
