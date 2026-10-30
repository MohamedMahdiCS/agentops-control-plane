from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.app.api.v1.agents import router as agents_router
from backend.app.api.v1.approvals import router as approvals_router
from backend.app.api.v1.benchmarks import router as benchmarks_router
from backend.app.api.v1.evaluations import router as evaluations_router
from backend.app.api.v1.overview import router as overview_router
from backend.app.api.v1.runs import router as runs_router
from backend.app.core.config import Settings, validate_runtime_settings
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


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    validate_runtime_settings(settings)
    production = settings.app_env == "production"

    application = FastAPI(
        title="AgentOps Control Plane API",
        version="0.1.0",
        description="Backend API for operating AI agents safely and reliably.",
        lifespan=lifespan,
        # Interactive documentation is a development aid, not a public surface.
        docs_url=None if production else "/docs",
        redoc_url=None if production else "/redoc",
        openapi_url=None if production else "/openapi.json",
    )

    origins = settings.allowed_origins()
    if origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
            allow_credentials=False,
            max_age=600,
        )

    @application.middleware("http")
    async def security_headers(request: Request, call_next) -> Response:
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if request.url.path.startswith("/api/"):
            # API responses can carry operator-only data; never cache them.
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    application.include_router(agents_router, prefix="/api/v1")
    application.include_router(runs_router, prefix="/api/v1")
    application.include_router(approvals_router, prefix="/api/v1")
    application.include_router(evaluations_router, prefix="/api/v1")
    application.include_router(benchmarks_router, prefix="/api/v1")
    application.include_router(overview_router, prefix="/api/v1")

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
