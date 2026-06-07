from __future__ import annotations

from datetime import datetime
import json
import re
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.models import JobRecord


JOB_TERMINAL_STATUSES = {"succeeded", "failed"}
JOB_ACTIVE_STATUSES = {"queued", "running"}


def to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _normalized_json_object(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def serialize_job_summary(job: JobRecord) -> dict[str, Any]:
    return {
        "id": job.id,
        "type": job.type,
        "workflow_key": job.workflow_key,
        "dataset_key": job.dataset_key,
        "status": job.status,
    }


def serialize_job_detail(job: JobRecord) -> dict[str, Any]:
    return {
        "id": job.id,
        "type": job.type,
        "workflow_key": job.workflow_key,
        "dataset_key": job.dataset_key,
        "status": job.status,
        "payload_json": _normalized_json_object(job.payload_json),
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "created_at": to_iso(job.created_at),
        "updated_at": to_iso(job.updated_at),
        "started_at": to_iso(job.started_at),
        "finished_at": to_iso(job.finished_at),
        "error": job.error,
        "result_json": _normalized_json_object(job.result_json),
    }


def apply_job_filters(
    stmt: Select[tuple[JobRecord]],
    *,
    job_type: str | None = None,
    workflow_key: str | None = None,
    dataset_key: str | None = None,
    status: str | None = None,
) -> Select[tuple[JobRecord]]:
    if job_type is not None:
        stmt = stmt.where(JobRecord.type == job_type)
    if workflow_key is not None:
        stmt = stmt.where(JobRecord.workflow_key == workflow_key)
    if dataset_key is not None:
        stmt = stmt.where(JobRecord.dataset_key == dataset_key)
    if status is not None:
        stmt = stmt.where(JobRecord.status == status)
    return stmt


def find_conflicting_job(
    session: Session,
    *,
    job_type: str,
    workflow_key: str | None = None,
    dataset_key: str | None = None,
    active_types: tuple[str, ...] | None = None,
) -> JobRecord | None:
    conflict_types = active_types or (job_type,)
    stmt = (
        select(JobRecord)
        .where(JobRecord.type.in_(conflict_types))
        .where(JobRecord.status.in_(sorted(JOB_ACTIVE_STATUSES)))
        .order_by(JobRecord.created_at.asc(), JobRecord.id.asc())
        .limit(1)
    )
    if workflow_key is not None:
        stmt = stmt.where(JobRecord.workflow_key == workflow_key)
    if dataset_key is not None:
        stmt = stmt.where(JobRecord.dataset_key == dataset_key)
    return session.scalar(stmt)


def _extract_numeric_suffix(value: str) -> int | None:
    match = re.search(r"(\d+)$", value)
    if match is None:
        return None
    return int(match.group(1))


def next_job_id(session: Session) -> str:
    next_id = 1
    for existing_id in session.scalars(select(JobRecord.id)).all():
        parsed = _extract_numeric_suffix(str(existing_id))
        if parsed is None:
            continue
        next_id = max(next_id, parsed + 1)
    return str(next_id)


def create_job(
    session: Session,
    *,
    job_type: str,
    status: str = "queued",
    payload_json: dict[str, Any] | None = None,
    workflow_key: str | None = None,
    dataset_key: str | None = None,
    max_attempts: int = 3,
    commit: bool = True,
) -> JobRecord:
    def _build() -> JobRecord:
        return JobRecord(
            id=next_job_id(session),
            type=job_type,
            workflow_key=workflow_key,
            dataset_key=dataset_key,
            status=status,
            payload_json=payload_json,
            attempts=0,
            max_attempts=max_attempts,
        )

    if not commit:
        # Inside a caller-managed transaction: a single flush. (The id-collision
        # retry below requires its own commit boundary, so it only applies to
        # the autocommit path.)
        job = _build()
        session.add(job)
        session.flush()
        return job

    # next_job_id() allocates ids by scanning max(suffix)+1, so two concurrent
    # enqueues can pick the same id and collide on the PK. Retry on the unique
    # violation, recomputing the id each attempt, instead of surfacing a 500.
    last_exc: IntegrityError | None = None
    for _ in range(8):
        job = _build()
        session.add(job)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            last_exc = exc
            continue
        session.refresh(job)
        return job
    assert last_exc is not None
    raise last_exc
