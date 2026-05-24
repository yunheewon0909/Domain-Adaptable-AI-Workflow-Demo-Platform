"""In-process background dispatcher for the `jobs` queue.

The platform has no separate worker process. Without a dispatcher, queue-backed
`ft_train_model` rows sit in `queued` forever. This module ships a small
asyncio loop that claims `queued` rows and runs the matching runner module.

Design:

- One dispatcher task per FastAPI process. Multi-worker uvicorn would race
  on the queue; the dispatcher uses a `SELECT ... FOR UPDATE SKIP LOCKED`-
  style claim where Postgres supports it. For SQLite tests (and Postgres
  fallback) it serializes via an in-process `asyncio.Lock`.
- The runner functions (e.g. `complete_training_job`) are synchronous and can
  spend minutes-hours inside an MLX subprocess. We dispatch them via
  `asyncio.to_thread()` so the event loop stays responsive for HTTP requests
  and concurrent jobs.
- Disable in tests by setting `FT_BACKGROUND_DISPATCH=false` before lifespan
  startup (the project conftest does this).

The dispatcher intentionally only handles `ft_train_model` for now; new
job types can register handlers in `_RUNNERS`.
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
from api.models import FTTrainingJobRecord, JobRecord


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


def _run_ft_training_job(payload: dict[str, Any]) -> None:
    """Sync runner for ft_train_model jobs. Runs in a worker thread."""
    from api.services.model_registry.service import complete_training_job

    training_job_id = str(payload.get("training_job_id") or "").strip()
    if not training_job_id:
        raise RuntimeError("ft_train_model payload missing training_job_id")
    with Session(get_engine()) as session:
        complete_training_job(session, training_job_id=training_job_id)


_RUNNERS: dict[str, Callable[[dict[str, Any]], None]] = {
    "ft_train_model": _run_ft_training_job,
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


_STALE_TRAINING_PHASES = (
    "preparing_data",
    "training",
    "packaging",
    "registering",
)


def reap_stale_training_jobs(session: Session) -> int:
    """Fail any FT training job stuck in a mid-flight phase without a running queue row.

    `complete_training_job` advances the domain row through `preparing_data →
    training → packaging → registering` while the backing `jobs` row holds
    `running`. If the API is killed mid-run, `reap_stale_running_jobs` flips
    the queue row to `failed`, but the FT training row stays in a mid-flight
    phase forever. Mark such rows `failed` with a crash_recovery error so
    reviewers can re-enqueue instead of waiting on a zombie.
    """
    stmt = select(FTTrainingJobRecord).where(
        FTTrainingJobRecord.status.in_(_STALE_TRAINING_PHASES)
    )
    rows = session.scalars(stmt).all()
    if not rows:
        return 0
    now = datetime.now(timezone.utc)
    reaped = 0
    for row in rows:
        backing_running = False
        if row.backing_job_id:
            backing = session.get(JobRecord, row.backing_job_id)
            backing_running = (
                backing is not None
                and backing.type == "ft_train_model"
                and backing.status == "running"
            )
        if backing_running:
            continue
        prior_phase = row.status
        row.status = "failed"
        row.finished_at = now
        row.error_json = {
            "category": "crash_recovery",
            "phase": prior_phase,
            "message": (
                "Training job left in a mid-flight phase by a previous API process; "
                "no running backing job exists. Re-enqueue to retry."
            ),
        }
        row.log_text = (
            (row.log_text or "")
            + "\nTraining job reaped on startup: no running backing job found."
        ).strip()
        reaped += 1
    if reaped:
        session.commit()
    return reaped


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
            # complete_training_job() already wrote a richer status to the
            # domain table; only the queue row needs to flip to succeeded.
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
