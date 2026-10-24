from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


def create_app() -> FastAPI:
    application = FastAPI(
        title="AgentOps Control Plane API",
        version="0.1.0",
        description="Backend API for operating AI agents safely and reliably.",
    )

    @application.get(
        "/api/v1/health",
        response_model=HealthResponse,
        tags=["Health"],
    )
    def health_check() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service="agentops-api",
            version="0.1.0",
        )

    return application


app = create_app()
