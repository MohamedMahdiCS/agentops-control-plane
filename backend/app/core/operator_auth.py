"""Server-verified operator authentication for sensitive API actions."""

import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.app.core.config import Settings

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class OperatorPrincipal:
    operator_id: str
    role: Literal["operator"] = "operator"


def require_operator(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
) -> OperatorPrincipal:
    """Authenticate using server configuration, never caller identity."""

    settings = Settings()
    stored_hash = settings.operator_token_sha256
    operator_id = settings.operator_id

    if (
        stored_hash is None
        or not operator_id
        or re.fullmatch(r"[A-Za-z0-9_.@:-]{1,128}", operator_id) is None
    ):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Operator authentication is not configured",
        )

    digest = stored_hash.get_secret_value()

    if re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Operator authentication is not configured",
        )

    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not 32 <= len(credentials.credentials) <= 256
    ):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid operator credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    supplied_hash = hashlib.sha256(credentials.credentials.encode("utf-8")).digest()

    if not hmac.compare_digest(supplied_hash, bytes.fromhex(digest)):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid operator credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return OperatorPrincipal(operator_id=operator_id)
