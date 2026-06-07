"""Background dispatcher for the `jobs` queue.

In the Docker deployment the dedicated `worker` container runs this loop
(``python -m api.worker``); for single-process local dev the API can run it
in-process. Without a dispatcher, queued rows sit in `queued` forever.

Design:

- The dispatcher claims `queued` rows with a `SELECT ... FOR UPDATE SKIP
  LOCKED` claim on Postgres; SQLite tests serialize via an in-process
  `asyncio.Lock`.
- Runner functions are synchronous and may run for minutes (graph indexing,
  evaluation runs). We dispatch them via `asyncio.to_thread()` so the event
  loop stays responsive.
- The in-process dispatcher is disabled with `FT_BACKGROUND_DISPATCH=false`
  (the API container and the project conftest set this); the worker entrypoint
  runs the loop unconditionally.

Job types register their runners in `_RUNNERS`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, timezone
import logging
import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.db import get_engine
from api.models import JobRecord


logger = logging.getLogger("api.background_runner")

_POLL_INTERVAL_SECONDS = float(os.getenv("FT_DISPATCH_POLL_INTERVAL", "2.0"))
_CLAIM_LOCK = asyncio.Lock()


def _background_dispatch_enabled() -> bool:
    return os.getenv("FT_BACKGROUND_DISPATCH", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _claim_next_queued_job(session: Session) -> JobRecord | None:
    """Atomically pick the next queued job and mark it running.

    Uses SELECT FOR UPDATE SKIP LOCKED on Postgres; on SQLite the in-process
    asyncio lock around the call provides equivalent serialization.
    """
    bind = session.get_bind()
    dialect = bind.dialect.name if bind is not None else ""

    stmt = (
        select(JobRecord)
        .where(JobRecord.status == "queued")
        .where(JobRecord.type.in_(tuple(_RUNNERS.keys())))
        .order_by(JobRecord.created_at.asc(), JobRecord.id.asc())
        .limit(1)
    )
    if dialect == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    job = session.scalar(stmt)
    if job is None:
        return None

    now = datetime.now(timezone.utc)
    job.status = "running"
    job.attempts = (job.attempts or 0) + 1
    job.started_at = now
    session.commit()
    return job


def _run_rag_index_collection(payload: dict[str, Any]) -> None:
    """Build the Graph RAG knowledge graph for a collection. Runs in a thread."""
    from api.services.rag.graph_index import index_collection

    collection_id = str(payload.get("collection_id") or "").strip()
    if not collection_id:
        raise RuntimeError("rag_index_collection payload missing collection_id")
    with Session(get_engine()) as session:
        index_collection(session, collection_id=collection_id)


# Job-type → runner registry. Evaluation runners register here too (Phase 7).
_RUNNERS: dict[str, Callable[[dict[str, Any]], None]] = {
    "rag_index_collection": _run_rag_index_collection,
}


def reap_unsupported_queue_rows(session: Session) -> int:
    """Mark queued/running rows whose `type` has no registered runner as failed.

    Legacy job types (e.g. `workflow_run` from the removed reviewer workflow
    surface) accumulate as zombies because the dispatcher's WHERE clause
    filters them out — they sit in `queued` forever. Run this once at
    startup to mark them terminal so the queue table stays honest.
    """
    supported = tuple(_RUNNERS.keys())
    stmt = select(JobRecord).where(
        JobRecord.status.in_(("queued", "running")),
        JobRecord.type.notin_(supported),
    )
    now = datetime.now(timezone.utc)
    rows = session.scalars(stmt).all()
    for row in rows:
        row.status = "failed"
        row.finished_at = now
        row.error = (
            f"job type '{row.type}' is no longer supported by the dispatcher "
            f"(known runners: {sorted(supported)})"
        )
    if rows:
        session.commit()
    return len(rows)


def reap_stale_running_jobs(session: Session) -> int:
    """Fail any `running` job left over from a previous API process.

    The dispatcher claims a job (status=running) then awaits the runner. If
    the API is killed mid-run, the row stays `running` forever — the next
    dispatcher cycle only looks at `queued`. Mark such rows as `failed`
    with a clear diagnostic so reviewers can re-enqueue if needed instead
    of waiting on a zombie.

    Limited to `_RUNNERS` types so `reap_unsupported_queue_rows` retains
    sole ownership of the legacy-type path.
    """
    supported = tuple(_RUNNERS.keys())
    if not supported:
        return 0
    stmt = select(JobRecord).where(
        JobRecord.status == "running",
        JobRecord.type.in_(supported),
    )
    now = datetime.now(timezone.utc)
    rows = session.scalars(stmt).all()
    for row in rows:
        row.status = "failed"
        row.finished_at = now
        row.error = (
            "Job left in `running` state by a previous API process. "
            "The dispatcher does not resume in-flight jobs; re-enqueue "
            "to retry."
        )
    if rows:
        session.commit()
    return len(rows)


async def _dispatch_one(job_id: str, job_type: str, payload: dict[str, Any]) -> None:
    """Run a single claimed job in a worker thread, recording outcome."""
    runner = _RUNNERS.get(job_type)
    if runner is None:
        # Unknown job type — leave as running so an operator can investigate.
        logger.warning("background dispatcher: no runner for job type=%s", job_type)
        return

    try:
        await asyncio.to_thread(runner, dict(payload))
    except Exception as exc:  # surface runner failures back to the queue row
        logger.exception("background runner for job %s failed", job_id)
        now = datetime.now(timezone.utc)
        with Session(get_engine()) as session:
            row = session.get(JobRecord, job_id)
            if row is not None:
                row.status = "failed"
                row.finished_at = now
                row.error = str(exc)[:4000]
                session.commit()
        return

    now = datetime.now(timezone.utc)
    with Session(get_engine()) as session:
        row = session.get(JobRecord, job_id)
        if row is not None and row.status == "running":
            # The runner may have written richer domain state already; only the
            # queue row needs to flip to succeeded here.
            row.status = "succeeded"
            row.finished_at = now
            session.commit()


async def dispatcher_loop(stop_event: asyncio.Event) -> None:
    """Poll the jobs table until `stop_event` is set.

    Each tick: claim one job (under the asyncio lock), dispatch it, loop.
    Sleeps `_POLL_INTERVAL_SECONDS` between empty polls so the queue table
    isn't hammered on an idle platform.
    """
    logger.info("background dispatcher started (poll=%.1fs)", _POLL_INTERVAL_SECONDS)
    while not stop_event.is_set():
        try:
            claimed_args: tuple[str, str, dict[str, Any]] | None = None
            async with _CLAIM_LOCK:
                with Session(get_engine()) as session:
                    job = _claim_next_queued_job(session)
                    if job is not None:
                        claimed_args = (
                            job.id,
                            job.type,
                            dict(job.payload_json)
                            if isinstance(job.payload_json, dict)
                            else {},
                        )
            if claimed_args is None:
                await asyncio.wait_for(stop_event.wait(), timeout=_POLL_INTERVAL_SECONDS)
                continue
            await _dispatch_one(*claimed_args)
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            raise
        except Exception:  # never let the loop die
            logger.exception("background dispatcher tick failed")
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
    logger.info("background dispatcher stopped")


def start_dispatcher_task(
    loop: asyncio.AbstractEventLoop | None = None,
) -> tuple[asyncio.Task[None] | None, asyncio.Event | None]:
    """Spawn the dispatcher as a managed background task.

    Returns (task, stop_event) when the dispatcher is enabled, (None, None)
    when disabled via env. The caller stores both and signals stop+await on
    shutdown.
    """
    if not _background_dispatch_enabled():
        logger.info("background dispatcher disabled (FT_BACKGROUND_DISPATCH=false)")
        return None, None
    stop_event = asyncio.Event()
    target_loop = loop or asyncio.get_running_loop()
    task = target_loop.create_task(dispatcher_loop(stop_event), name="ft-dispatcher")
    return task, stop_event


async def stop_dispatcher_task(
    task: asyncio.Task[None] | None, stop_event: asyncio.Event | None
) -> None:
    if stop_event is not None:
        stop_event.set()
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
