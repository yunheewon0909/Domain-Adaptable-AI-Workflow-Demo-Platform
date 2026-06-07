"""Worker-container entrypoint.

In the Docker-first deployment the long-running jobs (Graph RAG indexing,
evaluation runs) execute in a dedicated `worker` container rather than inside
the API process. This module runs the same dispatcher loop as the in-process
dispatcher (`services/background_runner.py`), reading the shared
`API_DATABASE_URL` and claiming `queued` rows from the `jobs` table.

The API container runs with the in-process dispatcher disabled
(`FT_BACKGROUND_DISPATCH=false`); this entrypoint runs the loop unconditionally
so the worker always processes the queue.

Run with: ``python -m api.worker``.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from api.services.background_runner import dispatcher_loop

logger = logging.getLogger("api.worker")


async def _run() -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:  # pragma: no cover - non-unix
            pass
    logger.info("worker starting; dispatching jobs from the shared queue")
    await dispatcher_loop(stop_event)
    logger.info("worker stopped")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run())


if __name__ == "__main__":
    main()
