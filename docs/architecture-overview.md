# AgentOps Control Plane — Architecture Overview

**Status:** Approved design — implementation pending

**Version:** 0.1

## 1. Purpose

AgentOps Control Plane is an AI engineering platform for discovering, executing, evaluating, observing, and securing AI agents.

Its central objective is to make agent behavior measurable, explainable, and controllable.

## 2. Initial Product Scope

The 15-day MVP will demonstrate a complete AI agent lifecycle using a simulated production incident-response environment.

The platform will provide:
- Agent registration and configuration tracking
- Bounded agent execution and tool orchestration
- Execution traces and operational metrics
- Deterministic agent evaluations
- Runtime policy enforcement
- Human approval workflows for sensitive simulated actions
- An interactive enterprise dashboard
- A reproducible benchmark framework: AgentOpsBench

## 3. Architecture

The system follows a modular monolith architecture.

### Frontend
React, TypeScript, Vite, Tailwind CSS, shadcn/ui, TanStack Query, TanStack Table, and Recharts.

### Backend
Python 3.12, FastAPI, Pydantic, and PostgreSQL.

### Core Backend Modules
- Agent Registry
- Agent Runtime
- Tool Gateway
- Trace and Observability Service
- Evaluation Engine
- Policy Engine
- Approval and Audit Service
- Benchmark Runner

### Execution Infrastructure
A database-backed worker processes durable agent runs and evaluations.

### AI Integration
A provider abstraction supports model-driven agent execution and deterministic test mode. The initial implementation prioritizes free/local execution.

## 4. Primary Workflow

1. Register a reference AI agent.
2. Submit a simulated incident.
3. Persist a queued execution.
4. Execute the agent through a bounded runtime.
5. Validate and authorize tool requests.
6. Record execution spans and policy decisions.
7. Pause approval-required actions.
8. Produce a final investigation outcome.
9. Grade the recorded execution.
10. Display evidence, findings, and benchmark results.

## 5. Reference Environment

A synthetic e-commerce infrastructure containing:
- Order Service
- Payment Service
- Simulated database dependency

The first incident concerns database connection-pool exhaustion.

All remediation actions are limited to simulated infrastructure.

## 6. Data Architecture

PostgreSQL stores agent registrations, executions, traces, evaluation cases and results, policies, decisions, approvals, and audit events.

Durable job state, idempotency, and benchmark persistence require additional implementation design before migrations are finalized.

## 7. Reliability and Security Principles

- Default-deny tool authorization
- Backend enforcement independent of AI instructions
- Strict input validation
- Idempotent simulated consequential actions
- Durable execution and approval state
- Redacted observability records
- Versioned evaluation rules
- Evidence-backed benchmark results
- Explicit error handling and audit records

## 8. Frontend

The application uses the Midnight Precision visual system with seven navigation sections:

1. Overview
2. Agents
3. Runs & Traces
4. Evaluations
5. Security
6. Approvals
7. Benchmarks

Run Details is the flagship investigation experience.

## 9. Implementation Boundaries

The initial MVP is a locally operated engineering demonstration, not a fully hardened multi-tenant production service.

Real infrastructure remediation, enterprise authentication, large-scale distributed processing, and broad production security certification are outside the initial scope.

## 10. Engineering Objective

Demonstrate practical skills in AI agent orchestration, backend architecture, evaluation infrastructure, observability, policy enforcement, reliability engineering, and frontend product development.
