from time import perf_counter

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.runtime.contracts import InvestigationCheckpoint
from backend.app.runtime.investigation import (
    ToolInvoker,
    execute_next_step,
)
from backend.app.runtime.plan import plan_for_incident
from backend.app.runtime.reporting import (
    build_investigation_report,
    format_report_summary,
)
from backend.app.services.run_checkpoints import save_run_checkpoint
from backend.app.services.run_claims import ClaimedRun
from backend.app.services.run_finalization import finalize_run
from backend.app.services.run_leases import renew_run_lease
from backend.app.services.tool_gateway import (
    GatewayApprovalRequired,
    GatewayDeniedError,
    GatewayOwnershipError,
    InvalidToolResultError,
    ToolGateway,
    ToolReportedTimeoutError,
)
from backend.app.simulator.faults import SimulatedRateLimitError, SimulatedToolError
from backend.app.simulator.registry import invoke_tool

ACTIVE_BUDGET_MS = 120_000
STEP_TIMEOUT_SECONDS = 15


async def process_claimed_run(
    session_factory: async_sessionmaker[AsyncSession],
    claim: ClaimedRun,
    *,
    tool_invoker: ToolInvoker = invoke_tool,
) -> bool:
    """Execute a claimed deterministic run with durable checkpoints.

    Return False if ownership is lost or finalization is rejected.
    Unexpected programming errors propagate for investigation.
    """
    started = perf_counter()
    gateway = ToolGateway(session_factory, claim, read_invoker=tool_invoker)

    async def execute_gateway_step(state, timeout_seconds):
        class DispatchRequested(Exception):
            pass

        request = None

        def capture_request(name, arguments):
            nonlocal request
            request = (name, arguments)
            raise DispatchRequested

        # Run the existing checkpoint, sequence, retry and budget checks before
        # authorizing or dispatching any tool.
        try:
            return execute_next_step(
                claim.incident_id, state, tool_invoker=capture_request
            )
        except DispatchRequested:
            pass

        name, arguments = request
        failure = None
        try:
            result = await gateway.invoke(
                name,
                arguments,
                checkpoint=state,
                active_elapsed_ms=elapsed_ms(),
                timeout_seconds=timeout_seconds,
            )
        except InvalidToolResultError:
            result = object()  # Existing checkpoint contract records invalid output.
        except ToolReportedTimeoutError:
            failure = TimeoutError("Tool timeout")
            result = None
        except (SimulatedRateLimitError, SimulatedToolError) as exc:
            failure = exc
            result = None

        def replay_result(name, arguments):
            if failure is not None:
                raise failure
            return result

        return execute_next_step(claim.incident_id, state, tool_invoker=replay_result)

    def elapsed_ms() -> int:
        return claim.active_elapsed_ms + int((perf_counter() - started) * 1000)

    async def fail(error_code: str) -> bool:
        async with session_factory() as session:
            return await finalize_run(
                session,
                claim,
                status="failed",
                error_code=error_code,
                result_summary="Investigation stopped safely.",
                active_elapsed_ms=elapsed_ms(),
            )

    if claim.execution_mode != "deterministic":
        return await fail("UNSUPPORTED_EXECUTION_MODE")

    try:
        plan = plan_for_incident(claim.incident_id)

        state = (
            InvestigationCheckpoint.model_validate(claim.execution_checkpoint)
            if claim.execution_checkpoint is not None
            else InvestigationCheckpoint(
                next_step=0,
                tool_calls_used=0,
            )
        )
    except (ValueError, ValidationError):
        return await fail("INVALID_EXECUTION_STATE")

    while state.next_step < len(plan):
        if elapsed_ms() >= ACTIVE_BUDGET_MS:
            return await fail("EXECUTION_TIME_BUDGET")

        # Keep the lease valid before executing each diagnostic step.
        # Renewal is fenced by worker identity and lease generation.
        async with session_factory() as session:
            renewed = await renew_run_lease(
                session,
                claim,
                lease_seconds=180,
            )

        if not renewed:
            # Ownership was lost or the existing lease expired.
            # Do not execute another tool or finalize this run.
            return False

        remaining_ms = ACTIVE_BUDGET_MS - elapsed_ms()

        if remaining_ms <= 0:
            return await fail("EXECUTION_TIME_BUDGET")

        timeout_seconds = min(
            STEP_TIMEOUT_SECONDS,
            remaining_ms / 1000,
        )

        total_budget_is_limiting = remaining_ms <= STEP_TIMEOUT_SECONDS * 1000

        try:
            updated = await execute_gateway_step(state, timeout_seconds)
        except GatewayOwnershipError:
            return False
        except GatewayApprovalRequired:
            return False
        except GatewayDeniedError:
            return await fail("TOOL_POLICY_DENIED")
        except TimeoutError:
            error_code = (
                "EXECUTION_TIME_BUDGET"
                if total_budget_is_limiting
                else "TOOL_STEP_TIMEOUT"
            )
            return await fail(error_code)
        except RuntimeError as exc:
            message = str(exc)

            if "retry limit" in message:
                return await fail("TOOL_RETRY_LIMIT")

            if "budget exhausted" in message:
                return await fail("TOOL_CALL_BUDGET")

            raise

        # Every successful or failed tool attempt is persisted
        # before the worker attempts the next diagnostic step.
        async with session_factory() as session:
            saved = await save_run_checkpoint(
                session,
                claim,
                updated.model_dump(mode="json"),
                active_elapsed_ms=elapsed_ms(),
            )

        if not saved:
            # The lease expired or another worker took ownership.
            # Never finalize a run using stale ownership.
            return False

        state = updated

        if elapsed_ms() >= ACTIVE_BUDGET_MS:
            return await fail("EXECUTION_TIME_BUDGET")

    try:
        report = build_investigation_report(
            claim.incident_id,
            state,
        )
    except (ValueError, ValidationError):
        return await fail("INVALID_INVESTIGATION_REPORT")

    summary = format_report_summary(report)

    async with session_factory() as session:
        return await finalize_run(
            session,
            claim,
            status="completed",
            result_summary=summary,
            active_elapsed_ms=elapsed_ms(),
        )
