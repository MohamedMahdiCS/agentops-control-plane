from typing import Literal

from pydantic import Field

from backend.app.simulator.registry import (
    TOOLS,
    UnknownToolError,
    invoke_tool,
)
from backend.app.simulator.schemas import SimulatorModel
from backend.app.simulator.tools import ApprovalRequiredError

ReadToolName = Literal[
    "get_incident",
    "get_service_health",
    "get_service_logs",
    "get_service_metrics",
    "get_service_dependencies",
]

FaultType = Literal["timeout", "rate_limit", "tool_error"]


class FaultSpec(SimulatorModel):
    tool_name: ReadToolName
    call_number: int = Field(ge=1, le=1000)
    fault_type: FaultType


class SimulatedRateLimitError(RuntimeError):
    pass


class SimulatedToolError(RuntimeError):
    pass


class FaultInjectingSimulator:
    """A deterministic, isolated tool failure test harness."""

    def __init__(self, faults: list[FaultSpec] | None = None):
        self._faults = {}
        self._calls: dict[str, int] = {}

        for fault in faults or []:
            key = (fault.tool_name, fault.call_number)

            if key in self._faults:
                raise ValueError("Duplicate fault specification")

            self._faults[key] = fault.fault_type

    def invoke(
        self,
        name: str,
        arguments: dict[str, object],
    ) -> SimulatorModel:
        definition = TOOLS.get(name)

        if definition is None:
            raise UnknownToolError(f"Unknown tool: {name}")

        validated = definition.input_schema.model_validate(arguments)

        if definition.permission != "read":
            raise ApprovalRequiredError(
                "Fault injection cannot authorize sensitive operations."
            )

        call_number = self._calls.get(name, 0) + 1
        self._calls[name] = call_number

        fault = self._faults.get((name, call_number))

        if fault == "timeout":
            raise TimeoutError("Simulated tool timeout")

        if fault == "rate_limit":
            raise SimulatedRateLimitError("Simulated tool rate limit")

        if fault == "tool_error":
            raise SimulatedToolError("Simulated internal tool failure")

        return invoke_tool(name, validated.model_dump())

    def reset(self) -> None:
        """Reset call counters for a reproducible test replay."""
        self._calls.clear()
