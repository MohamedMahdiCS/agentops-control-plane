from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_db_session(
    request: Request,
) -> AsyncIterator[AsyncSession]:
    session_factory = request.app.state.db_session_factory

    async with session_factory() as session:
        yield session
