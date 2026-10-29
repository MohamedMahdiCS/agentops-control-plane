"""Long-running investigation worker.

Claims queued runs from PostgreSQL (SKIP LOCKED leases) and executes them
through the deterministic runtime and Tool Gateway. Multiple workers can run
concurrently; leases and fencing generations prevent duplicate execution.

Run with: uv run python scripts/run_worker.py [--worker-id ID] [--poll-seconds N]
SIGINT/SIGTERM stop the loop after the current run finishes.
"""

import argparse
import asyncio
import logging
import signal
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.database import create_database_engine
from backend.app.core.session import create_session_factory
from backend.app.runtime.runner import run_worker_once

logger = logging.getLogger("agentops.worker")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AgentOps investigation worker")
    parser.add_argument(
        "--worker-id",
        default=f"worker-{socket.gethostname()}"[:128],
        help="Stable worker identity recorded on leases",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=2.0,
        help="Idle wait between queue checks (0.2-60)",
    )
    parser.add_argument(
        "--once", action="store_true", help="Process at most one run and exit"
    )
    args = parser.parse_args()
    if not 0.2 <= args.poll_seconds <= 60:
        parser.error("--poll-seconds must be between 0.2 and 60")
    return args


async def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)

    engine = create_database_engine()
    factory = create_session_factory(engine)
    logger.info("Worker %s started", args.worker_id)
    try:
        while not stop.is_set():
            try:
                result = await run_worker_once(factory, args.worker_id)
            except Exception:
                # Unexpected errors are logged and retried after a pause; the
                # run's lease expires and another worker can recover it.
                logger.exception("Worker cycle failed")
                result = None
            if result is not None and result.run_id is not None:
                logger.info(
                    "Processed run %s (finalized=%s)", result.run_id, result.finalized
                )
                if args.once:
                    break
                continue
            if args.once:
                break
            try:
                await asyncio.wait_for(stop.wait(), timeout=args.poll_seconds)
            except TimeoutError:
                pass
    finally:
        await engine.dispose()
        logger.info("Worker %s stopped", args.worker_id)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
