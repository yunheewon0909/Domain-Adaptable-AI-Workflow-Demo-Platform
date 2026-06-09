from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from api.db import Base, get_engine
from api.models import JobRecord
from api.services import background_runner
from api.services.background_runner import (
    _claim_next_queued_job,
    _dispatch_one,
    _RUNNERS,
    reap_stale_running_jobs,
    reap_unsupported_queue_rows,
    start_dispatcher_task,
)
from api.services.jobs import JobAborted, JobControl, create_job

JOB_TYPE = "test_job"


@pytest.fixture(autouse=True)
def fresh_sqlite_engine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    db = tmp_path / "background.db"
    monkeypatch.setenv("API_DATABASE_URL", f"sqlite+pysqlite:///{db}")
    get_engine.cache_clear()
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    yield
    engine.dispose()
    get_engine.cache_clear()


@pytest.fixture
def registered_runner() -> Iterator[list[dict[str, object]]]:
    """Register a no-op runner for `test_job` and clean it up afterwards."""
    calls: list[dict[str, object]] = []
    _RUNNERS[JOB_TYPE] = lambda payload, control=None: calls.append(payload)
    try:
        yield calls
    finally:
        _RUNNERS.pop(JOB_TYPE, None)


def _enqueue(job_type: str, payload: dict[str, object]) -> JobRecord:
    with Session(get_engine()) as session:
        job = create_job(session, job_type=job_type, payload_json=payload)
    return job


def test_claim_next_queued_job_picks_only_dispatchable_types(registered_runner) -> None:
    _enqueue(JOB_TYPE, {"k": "v"})
    _enqueue("unsupported_type", {"x": 1})
    with Session(get_engine()) as session:
        claimed = _claim_next_queued_job(session)
        assert claimed is not None
        assert claimed.type == JOB_TYPE
        assert claimed.status == "running"
        assert claimed.attempts == 1


def test_claim_next_queued_job_returns_none_when_no_queued_jobs() -> None:
    with Session(get_engine()) as session:
        assert _claim_next_queued_job(session) is None


def test_dispatch_one_marks_succeeded_on_runner_success(registered_runner) -> None:
    _enqueue(JOB_TYPE, {"id": "noop"})
    with Session(get_engine()) as session:
        claimed = _claim_next_queued_job(session)
        assert claimed is not None
        claim_id = claimed.id
        payload = dict(claimed.payload_json or {})
    asyncio.run(_dispatch_one(claim_id, JOB_TYPE, payload))
    with Session(get_engine()) as session:
        row = session.get(JobRecord, claim_id)
        assert row is not None
        assert row.status == "succeeded"
        assert row.finished_at is not None
    assert registered_runner == [{"id": "noop"}]


def _boom(payload: dict[str, object], control: object = None) -> None:
    raise RuntimeError("runner exploded")


def test_dispatch_one_requeues_on_runner_exception_when_attempts_available() -> None:
    # Default max_attempts=3, so the first failure (attempts==1) is requeued.
    _enqueue(JOB_TYPE, {"id": "bad"})
    _RUNNERS[JOB_TYPE] = _boom
    try:
        with Session(get_engine()) as session:
            claimed = _claim_next_queued_job(session)
            assert claimed is not None
            claim_id = claimed.id
            payload = dict(claimed.payload_json or {})
        asyncio.run(_dispatch_one(claim_id, JOB_TYPE, payload))
        with Session(get_engine()) as session:
            row = session.get(JobRecord, claim_id)
            assert row is not None
            assert row.status == "queued"
            assert row.attempts == 1
            assert "runner exploded" in (row.error or "")
            assert row.finished_at is None
    finally:
        _RUNNERS.pop(JOB_TYPE, None)


def test_dispatch_one_marks_failed_when_max_attempts_exceeded() -> None:
    with Session(get_engine()) as session:
        job = create_job(session, job_type=JOB_TYPE, payload_json={}, max_attempts=1)
        claim_id = job.id
    _RUNNERS[JOB_TYPE] = _boom
    try:
        with Session(get_engine()) as session:
            claimed = _claim_next_queued_job(session)  # attempts -> 1 == max_attempts
            assert claimed is not None
            payload = dict(claimed.payload_json or {})
        asyncio.run(_dispatch_one(claim_id, JOB_TYPE, payload))
        with Session(get_engine()) as session:
            row = session.get(JobRecord, claim_id)
            assert row is not None
            assert row.status == "failed"
            assert row.attempts == 1
            assert row.finished_at is not None
    finally:
        _RUNNERS.pop(JOB_TYPE, None)


def _abort(reason: str):
    def _runner(payload: dict[str, object], control: object = None) -> None:
        raise JobAborted(reason)

    return _runner


def test_dispatch_one_requeues_on_timeout_when_attempts_available() -> None:
    _enqueue(JOB_TYPE, {})
    _RUNNERS[JOB_TYPE] = _abort("timeout")
    try:
        with Session(get_engine()) as session:
            claimed = _claim_next_queued_job(session)
            assert claimed is not None
            claim_id = claimed.id
        asyncio.run(_dispatch_one(claim_id, JOB_TYPE, {}))
        with Session(get_engine()) as session:
            row = session.get(JobRecord, claim_id)
            assert row is not None
            assert row.status == "queued"
            assert "timed out" in (row.error or "")
    finally:
        _RUNNERS.pop(JOB_TYPE, None)


def test_dispatch_one_marks_cancelled_on_cooperative_cancel() -> None:
    _enqueue(JOB_TYPE, {})
    _RUNNERS[JOB_TYPE] = _abort("cancelled")
    try:
        with Session(get_engine()) as session:
            claimed = _claim_next_queued_job(session)
            assert claimed is not None
            claim_id = claimed.id
        asyncio.run(_dispatch_one(claim_id, JOB_TYPE, {}))
        with Session(get_engine()) as session:
            row = session.get(JobRecord, claim_id)
            assert row is not None
            assert row.status == "cancelled"
            assert row.finished_at is not None
    finally:
        _RUNNERS.pop(JOB_TYPE, None)


def test_retry_cycle_then_success(registered_runner) -> None:
    # claim -> fail -> requeue -> claim -> succeed; ends succeeded with attempts==2.
    _enqueue(JOB_TYPE, {"id": "noop"})
    _RUNNERS[JOB_TYPE] = _boom
    with Session(get_engine()) as session:
        claimed = _claim_next_queued_job(session)
        assert claimed is not None
        claim_id = claimed.id
    asyncio.run(_dispatch_one(claim_id, JOB_TYPE, {}))
    with Session(get_engine()) as session:
        assert session.get(JobRecord, claim_id).status == "queued"  # type: ignore[union-attr]

    # Second attempt succeeds (registered_runner is the recording no-op).
    _RUNNERS[JOB_TYPE] = lambda payload, control=None: registered_runner.append(payload)
    with Session(get_engine()) as session:
        claimed = _claim_next_queued_job(session)
        assert claimed is not None
    asyncio.run(_dispatch_one(claim_id, JOB_TYPE, {}))
    with Session(get_engine()) as session:
        row = session.get(JobRecord, claim_id)
        assert row is not None
        assert row.status == "succeeded"
        assert row.attempts == 2


def test_job_control_check_raises_timeout_and_cancelled(registered_runner) -> None:
    from datetime import datetime, timedelta, timezone

    with Session(get_engine()) as session:
        job = create_job(session, job_type=JOB_TYPE, payload_json={})
        job.status = "running"
        session.commit()
        job_id = job.id

    # No deadline + no cancel flag -> no-op.
    JobControl(job_id=job_id).check()

    # Past deadline -> timeout.
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    try:
        JobControl(job_id=job_id, deadline=past).check()
        raise AssertionError("expected JobAborted(timeout)")
    except JobAborted as exc:
        assert exc.reason == "timeout"

    # cancel_requested_at set -> cancelled (read via a fresh session).
    with Session(get_engine()) as session:
        row = session.get(JobRecord, job_id)
        assert row is not None
        row.cancel_requested_at = datetime.now(timezone.utc)
        session.commit()
    try:
        JobControl(job_id=job_id).check()
        raise AssertionError("expected JobAborted(cancelled)")
    except JobAborted as exc:
        assert exc.reason == "cancelled"


def test_reap_stale_running_jobs_requeues_when_attempts_available(registered_runner) -> None:
    # A worker-crash zombie with attempts remaining is requeued, not lost.
    with Session(get_engine()) as session:
        job = create_job(session, job_type=JOB_TYPE, payload_json={})
        job.status = "running"
        job.attempts = 1  # one attempt consumed by the crashed run
        session.commit()
        claim_id = job.id

    with Session(get_engine()) as session:
        assert reap_stale_running_jobs(session) == 1

    with Session(get_engine()) as session:
        row = session.get(JobRecord, claim_id)
        assert row is not None
        assert row.status == "queued"
        assert "previous worker process" in (row.error or "")


def test_reap_stale_running_jobs_fails_when_attempts_exhausted(registered_runner) -> None:
    with Session(get_engine()) as session:
        job = create_job(
            session, job_type=JOB_TYPE, payload_json={}, max_attempts=1
        )
        job.status = "running"
        job.attempts = 1
        session.commit()
        claim_id = job.id

    with Session(get_engine()) as session:
        assert reap_stale_running_jobs(session) == 1

    with Session(get_engine()) as session:
        row = session.get(JobRecord, claim_id)
        assert row is not None
        assert row.status == "failed"
        assert row.finished_at is not None


def test_reap_stale_running_jobs_marks_cancelled_when_requested(registered_runner) -> None:
    from datetime import datetime, timezone

    with Session(get_engine()) as session:
        job = create_job(session, job_type=JOB_TYPE, payload_json={})
        job.status = "running"
        job.attempts = 1
        job.cancel_requested_at = datetime.now(timezone.utc)
        session.commit()
        claim_id = job.id

    with Session(get_engine()) as session:
        assert reap_stale_running_jobs(session) == 1

    with Session(get_engine()) as session:
        row = session.get(JobRecord, claim_id)
        assert row is not None
        assert row.status == "cancelled"


def test_reap_stale_running_jobs_leaves_queued_and_succeeded_alone(registered_runner) -> None:
    with Session(get_engine()) as session:
        queued = create_job(session, job_type=JOB_TYPE, payload_json={})
        succeeded = create_job(session, job_type=JOB_TYPE, payload_json={})
        succeeded.status = "succeeded"
        session.commit()
        queued_id, succeeded_id = queued.id, succeeded.id

    with Session(get_engine()) as session:
        assert reap_stale_running_jobs(session) == 0

    with Session(get_engine()) as session:
        assert session.get(JobRecord, queued_id).status == "queued"  # type: ignore[union-attr]
        assert session.get(JobRecord, succeeded_id).status == "succeeded"  # type: ignore[union-attr]


def test_reap_unsupported_queue_rows_fails_legacy_types(registered_runner) -> None:
    with Session(get_engine()) as session:
        legacy = create_job(session, job_type="workflow_run", payload_json={"key": "v1"})
        modern = create_job(session, job_type=JOB_TYPE, payload_json={"id": "y"})
        legacy_id, modern_id = legacy.id, modern.id

    with Session(get_engine()) as session:
        assert reap_unsupported_queue_rows(session) == 1

    with Session(get_engine()) as session:
        legacy_row = session.get(JobRecord, legacy_id)
        assert legacy_row is not None
        assert legacy_row.status == "failed"
        assert "no longer supported" in (legacy_row.error or "")
        modern_row = session.get(JobRecord, modern_id)
        assert modern_row is not None
        assert modern_row.status == "queued"


def test_start_dispatcher_returns_none_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FT_BACKGROUND_DISPATCH", "false")
    task, stop_event = start_dispatcher_task()
    assert task is None
    assert stop_event is None


def test_start_dispatcher_returns_task_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FT_BACKGROUND_DISPATCH", "true")

    async def _run() -> None:
        task, stop_event = start_dispatcher_task()
        assert task is not None
        assert stop_event is not None
        stop_event.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_run())
