import asyncio
import os

import pytest
from sqlalchemy import text

from backend.app.core.database import create_database_engine
from backend.app.core.session import create_session_factory


def test_async_database_session_executes_query() -> None:
    if os.getenv("AGENTOPS_RUN_DB_INTEGRATION") != "1":
        pytest.skip("Database integration tests require explicit activation")

    async def verify_connection() -> None:
        engine = create_database_engine()

        try:
            factory = create_session_factory(engine)

            async with factory() as session:
                result = await session.execute(text("SELECT 1"))

                assert result.scalar_one() == 1
        finally:
            await engine.dispose()

    asyncio.run(verify_connection())
