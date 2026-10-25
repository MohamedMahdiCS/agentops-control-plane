import os
from typing import Annotated

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.dependencies import get_db_session
from backend.app.main import create_app


def test_fastapi_database_dependency() -> None:
    if os.getenv("AGENTOPS_RUN_DB_INTEGRATION") != "1":
        pytest.skip("Database integration tests require explicit activation")

    app = create_app()

    @app.get("/__test/db-dependency", include_in_schema=False)
    async def database_endpoint(
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> dict[str, int]:
        result = await session.scalar(text("SELECT 1"))
        return {"database_result": result}

    with TestClient(app) as client:
        assert hasattr(app.state, "db_session_factory")

        response = client.get("/__test/db-dependency")

        assert response.status_code == 200
        assert response.json() == {"database_result": 1}
