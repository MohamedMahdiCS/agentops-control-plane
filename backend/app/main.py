from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from backend.app.api.v1.agents import router as agents_router
from backend.app.api.v1.approvals import router as approvals_router
from backend.app.api.v1.runs import router as runs_router
from backend.app.core.database import create_database_engine
from backend.app.core.session import create_session_factory


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    engine = create_database_engine()
    application.state.db_session_factory = create_session_factory(engine)

    try:
        yield
    finally:
        await engine.dispose()


def create_app() -> FastAPI:
    application = FastAPI(
        title="AgentOps Control Plane API",
        version="0.1.0",
        description="Backend API for operating AI agents safely and reliably.",
        lifespan=lifespan,
    )

    application.include_router(agents_router, prefix="/api/v1")
    application.include_router(runs_router, prefix="/api/v1")
    application.include_router(approvals_router, prefix="/api/v1")

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
