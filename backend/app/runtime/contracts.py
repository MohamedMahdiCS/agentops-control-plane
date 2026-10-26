from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.simulator.faults import ReadToolName

RootCauseCode = Literal[
    "DB_CONNECTION_POOL_EXHAUSTION",
    "INSUFFICIENT_EVIDENCE",
]

Confidence = Literal[
    "high",
    "medium",
    "low",
    "insufficient",
]


class RuntimeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EvidenceRecord(RuntimeModel):
    evidence_id: str = Field(pattern=r"^E[0-9]{3}$")
    tool_name: ReadToolName
    arguments: dict[str, object]
    observation: dict[str, object]


FailureCode = Literal[
    "TOOL_TIMEOUT",
    "TOOL_RATE_LIMITED",
    "TOOL_ERROR",
    "INVALID_TOOL_RESULT",
]


class ToolFailureRecord(RuntimeModel):
    step_index: int = Field(ge=0, le=9)
    call_number: int = Field(ge=1, le=10)
    tool_name: ReadToolName
    error_code: FailureCode


class InvestigationCheckpoint(RuntimeModel):
    version: Literal[1] = 1
    next_step: int = Field(ge=0, le=10)
    tool_calls_used: int = Field(ge=0, le=10)
    evidence: list[EvidenceRecord] = Field(
        default_factory=list,
        max_length=10,
    )
    failed_attempts: list[ToolFailureRecord] = Field(
        default_factory=list,
        max_length=10,
    )


class InvestigationReport(RuntimeModel):
    incident_id: str = Field(min_length=5, max_length=64)
    root_cause_code: RootCauseCode
    diagnosis: str = Field(min_length=10, max_length=1000)
    confidence: Confidence
    evidence_ids: list[str] = Field(min_length=1, max_length=10)
    recommendation: str = Field(min_length=10, max_length=1000)
