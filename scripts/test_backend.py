"""Run the backend suite only after verifying the isolated database identity.

Run with: uv run python scripts/test_backend.py
Credentials are passed through the child environment, never printed.
"""

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.config import Settings


def main():
    test_url = make_url(Settings().database_url.get_secret_value()).set(
        database="agentops_test"
    )
    engine = create_engine(test_url)
    try:
        with engine.connect() as connection:
            if connection.scalar(text("SELECT current_database()")) != "agentops_test":
                raise RuntimeError("Refusing tests outside agentops_test")
    finally:
        engine.dispose()
    print("Verified isolated agentops_test database", flush=True)
    env = os.environ.copy()
    env["DATABASE_URL"] = test_url.render_as_string(hide_password=False)
    env["AGENTOPS_RUN_DB_INTEGRATION"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *sys.argv[1:]], env=env, check=False
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
