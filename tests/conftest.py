"""Refuse all opt-in database tests outside the isolated test database."""

import os

import pytest
from sqlalchemy.engine import make_url

from backend.app.core.config import Settings


def pytest_sessionstart(session):
    if os.getenv("AGENTOPS_RUN_DB_INTEGRATION") == "1":
        url = make_url(Settings().database_url.get_secret_value())
        if url.database != "agentops_test":
            raise pytest.UsageError("Database integration tests require agentops_test")
