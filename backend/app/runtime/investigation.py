from collections.abc import Callable

from pydantic import ValidationError

from backend.app.runtime.contracts import (
    EvidenceRecord,
    InvestigationCheckpoint,
    ToolFailureRecord,
)
from backend.app.runtime.plan import (
    MAX_DIAGNOSTIC_CALLS,
    plan_for_incident,
)
from backend.app.simulator.faults import (
    SimulatedRateLimitError,
    SimulatedToolError,
)
from backend.app.simulator.registry import TOOLS, invoke_tool
from backend.app.simulator.schemas import SimulatorModel

ToolInvoker = Callable[
    [str, dict[str, object]],
    SimulatorModel,
]

MAX_RETRIES_PER_STEP = 2


def execute_next_step(
    incident_id: str,
    checkpoint: InvestigationCheckpoint | None = None,
    *,
    tool_invoker: ToolInvoker = invoke_tool,
) -> InvestigationCheckpoint:
    """Execute one attempt and return its updated checkpoint."""
    plan = plan_for_incident(incident_id)

    state = (
        checkpoint.model_copy(deep=True)
        if checkpoint is not None
        else InvestigationCheckpoint(
            next_step=0,
            tool_calls_used=0,
        )
    )

    if state.next_step != len(state.evidence):
        raise ValueError("Checkpoint step/evidence mismatch")

    if state.next_step > len(plan):
        raise ValueError("Checkpoint exceeds investigation plan")

    if state.tool_calls_used != (len(state.evidence) + len(state.failed_attempts)):
        raise ValueError("Checkpoint attempt count mismatch")

    for index, evidence in enumerate(state.evidence):
        expected = plan[index]

        if (
            evidence.evidence_id != f"E{index + 1:03d}"
            or evidence.tool_name != expected.tool_name
            or evidence.arguments != expected.arguments
        ):
            raise ValueError("Checkpoint evidence sequence mismatch")

    seen_calls = set()

    for failure in state.failed_attempts:
        if (
            failure.step_index >= len(plan)
            or failure.step_index > state.next_step
            or failure.tool_name != plan[failure.step_index].tool_name
            or failure.call_number > state.tool_calls_used
            or failure.call_number in seen_calls
        ):
            raise ValueError("Invalid checkpoint failure history")

        seen_calls.add(failure.call_number)

    if state.next_step == len(plan):
        return state

    if state.tool_calls_used >= MAX_DIAGNOSTIC_CALLS:
        raise RuntimeError("Diagnostic tool-call budget exhausted")

    failures_on_step = sum(
        failure.step_index == state.next_step for failure in state.failed_attempts
    )

    if failures_on_step > MAX_RETRIES_PER_STEP:
        raise RuntimeError("Diagnostic step retry limit exceeded")

    step = plan[state.next_step]
    definition = TOOLS[step.tool_name]

    if definition.permission != "read":
        raise RuntimeError("Sensitive diagnostic step rejected")

    arguments = dict(step.arguments)
    call_number = state.tool_calls_used + 1
    error_code = None

    try:
        result = tool_invoker(step.tool_name, arguments)
    except TimeoutError:
        error_code = "TOOL_TIMEOUT"
    except SimulatedRateLimitError:
        error_code = "TOOL_RATE_LIMITED"
    except SimulatedToolError:
        error_code = "TOOL_ERROR"
    else:
        if definition.output_schema is None:
            raise RuntimeError("Missing diagnostic output contract")

        try:
            validated = definition.output_schema.model_validate(result.model_dump())
        except (ValidationError, AttributeError, TypeError):
            error_code = "INVALID_TOOL_RESULT"

    if error_code is not None:
        failure = ToolFailureRecord(
            step_index=state.next_step,
            call_number=call_number,
            tool_name=step.tool_name,
            error_code=error_code,
        )

        return InvestigationCheckpoint(
            version=1,
            next_step=state.next_step,
            tool_calls_used=call_number,
            evidence=state.evidence,
            failed_attempts=[
                *state.failed_attempts,
                failure,
            ],
        )

    evidence = EvidenceRecord(
        evidence_id=f"E{state.next_step + 1:03d}",
        tool_name=step.tool_name,
        arguments=arguments,
        observation=validated.model_dump(mode="json"),
    )

    return InvestigationCheckpoint(
        version=1,
        next_step=state.next_step + 1,
        tool_calls_used=call_number,
        evidence=[*state.evidence, evidence],
        failed_attempts=state.failed_attempts,
    )
