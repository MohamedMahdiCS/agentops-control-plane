"""Backend-only authorization boundary for the synthetic tool environment.

No caller-supplied approval flag or permission can authorize a mutation.
Authorization and audit intent commit before dispatch. A missing outcome after
a crash means unknown completion, never inferred success.
"""

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from time import perf_counter
from typing import Literal
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.models.agent_run import AgentRun
from backend.app.models.approval_request import ApprovalRequest
from backend.app.models.audit_event import AuditEvent
from backend.app.models.policy_decision import PolicyDecision
from backend.app.models.trace_span import TraceSpan
from backend.app.runtime.contracts import InvestigationCheckpoint
from backend.app.runtime.investigation import ToolInvoker
from backend.app.services.run_claims import ClaimedRun
from backend.app.simulator.registry import TOOLS, invoke_tool
from backend.app.simulator.scenarios import INCIDENTS, SERVICE_DEPENDENCIES
from backend.app.simulator.schemas import SimulatorModel


class GatewayDeniedError(PermissionError):
    pass


class GatewayOwnershipError(PermissionError):
    pass


class GatewayApprovalRequired(GatewayDeniedError):
    pass


class InvalidToolResultError(ValueError):
    pass


class ToolReportedTimeoutError(Exception):
    """A tool failure, distinct from the gateway's enforced deadline."""


@dataclass(frozen=True)
class Authorization:
    action: str
    resource: str
    decision: Literal["allow", "deny", "require_approval"]
    reason_code: str
    arguments: dict[str, object]


def _incident_service_scope(incident_id: str) -> set[str]:
    """Affected services plus transitive dependencies, deny unknown incidents."""
    incident = INCIDENTS.get(incident_id)
    if incident is None:
        return set()

    allowed = set(incident.affected_services)
    pending = list(allowed)

    while pending:
        service = pending.pop()
        observation = SERVICE_DEPENDENCIES.get(service)
        if observation is None:
            continue

        for dependency in observation.dependencies:
            if dependency not in allowed:
                allowed.add(dependency)
                pending.append(dependency)

    return allowed


def evaluate_request(
    name: str, arguments: dict[str, object], incident_id: str
) -> Authorization:
    """Fixed v1 policy; registry metadata is trusted, request text is not."""
    definition = TOOLS.get(name) if isinstance(name, str) else None
    if definition is None:
        return Authorization("unregistered", "unknown", "deny", "UNKNOWN_TOOL", {})
    try:
        if type(arguments) is not dict:
            raise ValueError("Arguments must be an object")
        validated = definition.input_schema.model_validate(arguments).model_dump()
    except (ValidationError, ValueError, TypeError):
        return Authorization(name, "unknown", "deny", "INVALID_ARGUMENTS", {})

    resource = str(validated.get("service_name", validated.get("incident_id")))
    if name == "get_incident" and (
        resource != incident_id or resource not in INCIDENTS
    ):
        return Authorization(name, "unknown", "deny", "RESOURCE_OUT_OF_SCOPE", {})
    if "service_name" in validated and validated[
        "service_name"
    ] not in _incident_service_scope(incident_id):
        return Authorization(name, "unknown", "deny", "RESOURCE_OUT_OF_SCOPE", {})
    if definition.permission == "read" and definition.output_schema is not None:
        return Authorization(name, resource, "allow", "READ_ONLY_V1", validated)
    if name == "restart_service" and definition.permission == "require_approval":
        return Authorization(
            name,
            resource,
            "require_approval",
            "OPERATOR_APPROVAL_REQUIRED_V1",
            validated,
        )
    return Authorization(name, "unknown", "deny", "DEFAULT_DENY", {})


class ToolGateway:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        claim: ClaimedRun,
        *,
        read_invoker: ToolInvoker = invoke_tool,
    ):
        self.session_factory = session_factory
        self.claim = claim
        # Trusted simulator/fault-injection adapter, never supplied by an agent.
        self.read_invoker = read_invoker

    def _audit(self, event_type: str, decision_id: UUID, payload: dict) -> AuditEvent:
        return AuditEvent(
            run_id=self.claim.run_id,
            actor_type="worker",
            actor_identifier=self.claim.worker_id,
            event_type=event_type,
            resource_type="policy_decision",
            resource_id=str(decision_id),
            event_payload=payload,
        )

    async def invoke(
        self,
        name: str,
        arguments: dict[str, object],
        *,
        checkpoint: InvestigationCheckpoint,
        active_elapsed_ms: int,
        timeout_seconds: float = 15,
    ) -> SimulatorModel:
        if type(active_elapsed_ms) is not int or active_elapsed_ms < 0:
            raise ValueError("Invalid active elapsed time")
        if not 0 < timeout_seconds <= 120:
            raise ValueError("Invalid tool timeout")
        # Serialize/validate before any database operation or dispatch.
        saved_checkpoint = InvestigationCheckpoint.model_validate(
            checkpoint.model_dump()
        ).model_dump(mode="json")
        decision_id, span_id = uuid4(), uuid4()
        async with self.session_factory() as session, session.begin():
            run = await session.scalar(
                select(AgentRun)
                .where(AgentRun.id == self.claim.run_id)
                .with_for_update()
            )
            now = await session.scalar(select(func.clock_timestamp()))
            if (
                run is None
                or run.status != "running"
                or run.lease_owner != self.claim.worker_id
                or run.lease_generation != self.claim.lease_generation
                or run.lease_expires_at is None
                or now is None
                or run.lease_expires_at <= now
                or run.checkpoint_version != 1
            ):
                raise GatewayOwnershipError("Tool request has no live worker ownership")
            authorization = evaluate_request(name, arguments, run.incident_id)
            session.add(
                TraceSpan(
                    id=span_id,
                    run_id=run.id,
                    span_type="tool_call",
                    name=authorization.action,
                    status="running"
                    if authorization.decision == "allow"
                    else "blocked",
                    ended_at=None if authorization.decision == "allow" else now,
                    sanitized_attributes={"resource": authorization.resource},
                )
            )
            await session.flush()
            session.add(
                PolicyDecision(
                    id=decision_id,
                    run_id=run.id,
                    trace_span_id=span_id,
                    action=authorization.action,
                    resource=authorization.resource,
                    decision=authorization.decision,
                    reason_code=authorization.reason_code,
                    executed=False,
                )
            )
            await session.flush()
            session.add(
                self._audit(
                    "tool.authorization",
                    decision_id,
                    {
                        "action": authorization.action,
                        "resource": authorization.resource,
                        "decision": authorization.decision,
                        "reason_code": authorization.reason_code,
                        "policy_version": 1,
                        "lease_generation": self.claim.lease_generation,
                    },
                )
            )
            if authorization.decision == "require_approval":
                approval_id = uuid4()
                session.add(
                    ApprovalRequest(
                        id=approval_id,
                        run_id=run.id,
                        policy_decision_id=decision_id,
                        action=authorization.action,
                        resource=authorization.resource,
                        validated_action_arguments=authorization.arguments,
                        action_execution_key=str(uuid4()),
                        risk_level="high",
                        reason="Simulated service restart requires operator approval.",
                        status="pending",
                        execution_status="not_started",
                        expires_at=now + timedelta(minutes=15),
                    )
                )
                await session.flush()
                run.execution_checkpoint = saved_checkpoint
                run.active_elapsed_ms = max(run.active_elapsed_ms, active_elapsed_ms)
                run.pending_approval_id = approval_id
                run.status = "awaiting_approval"
                run.lease_owner = None
                run.lease_expires_at = None
                session.add(
                    self._audit(
                        "tool.approval_requested",
                        decision_id,
                        {
                            "approval_id": str(approval_id),
                            "executed": False,
                        },
                    )
                )

        # This point is reached only after durable intent/audit commit succeeds.
        if authorization.decision == "require_approval":
            raise GatewayApprovalRequired("Operator approval required")
        if authorization.decision != "allow":
            raise GatewayDeniedError(authorization.reason_code)

        started = perf_counter()
        outcome = "TOOL_ERROR"
        executed = False

        def dispatch_read():
            try:
                return self.read_invoker(name, dict(authorization.arguments))
            except TimeoutError:
                raise ToolReportedTimeoutError from None

        try:
            # Only the five registered read tools can reach this adapter.
            executed = True
            result = await asyncio.wait_for(
                asyncio.to_thread(dispatch_read),
                timeout=timeout_seconds,
            )
            definition = TOOLS[name]
            try:
                validated_result = definition.output_schema.model_validate(
                    result.model_dump()
                )
                # Reject observations for a different resource/window.
                for key in ("service_name", "incident_id", "lookback_minutes"):
                    if key in authorization.arguments and (
                        getattr(validated_result, key, None)
                        != authorization.arguments[key]
                    ):
                        raise ValueError("Mismatched observation resource")
            except (ValidationError, AttributeError, TypeError, ValueError):
                outcome = "INVALID_TOOL_RESULT"
                raise InvalidToolResultError(outcome) from None
            outcome = "SUCCESS"
            return validated_result
        except ToolReportedTimeoutError:
            outcome = "TOOL_TIMEOUT"
            raise
        except TimeoutError:
            outcome = "TOOL_TIMEOUT_UNKNOWN_COMPLETION"
            raise
        except asyncio.CancelledError:
            outcome = "TOOL_CANCELLED_UNKNOWN_COMPLETION"
            raise
        finally:
            # Never include raw arguments, responses, validation errors or exception text.
            async with self.session_factory() as session, session.begin():
                decision = await session.get(PolicyDecision, decision_id)
                span = await session.get(TraceSpan, span_id)
                decision.executed = executed
                span.status = "ok" if outcome == "SUCCESS" else "error"
                span.ended_at = await session.scalar(select(func.clock_timestamp()))
                span.duration_ms = int((perf_counter() - started) * 1000)
                span.safe_summary = outcome
                session.add(
                    self._audit(
                        "tool.outcome",
                        decision_id,
                        {
                            "outcome": outcome,
                            "dispatched": executed,
                        },
                    )
                )
