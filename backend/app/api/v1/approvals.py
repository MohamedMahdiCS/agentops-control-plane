"""Authenticated human-approval decision endpoints."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.dependencies import get_db_session
from backend.app.core.operator_auth import (
    OperatorPrincipal,
    require_operator,
)
from backend.app.services.approval_decisions import (
    ApprovalConflictError,
    ApprovalNotFoundError,
    decide_pending_approval,
)

router = APIRouter(tags=["Human Approvals"])


class ApprovalDecisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    decision: Literal["approved", "rejected"]
    reason: str = Field(min_length=10, max_length=1000)


class ApprovalDecisionResponse(BaseModel):
    approval_id: UUID
    status: str
    run_status: str
    idempotent: bool


@router.post(
    "/approvals/{approval_id}/decision",
    response_model=ApprovalDecisionResponse,
)
async def submit_approval_decision(
    approval_id: UUID,
    payload: ApprovalDecisionPayload,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[
        OperatorPrincipal,
        Depends(require_operator),
    ],
    idempotency_key: Annotated[
        str,
        Header(min_length=8, max_length=128),
    ],
) -> ApprovalDecisionResponse:
    """Record a verified operator decision without dispatching tools."""

    try:
        result = await decide_pending_approval(
            session,
            approval_id,
            decision=payload.decision,
            operator_id=principal.operator_id,
            reason=payload.reason,
            idempotency_key=idempotency_key,
        )
    except ApprovalNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="Approval request not found",
        ) from exc
    except ApprovalConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail="Approval request cannot be decided",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="Invalid approval decision parameters",
        ) from exc

    return ApprovalDecisionResponse(
        approval_id=result.approval_id,
        status=result.status,
        run_status=result.run_status,
        idempotent=result.idempotent,
    )
