from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.db import get_engine
from api.models import JobRecord
from api.services.jobs import (
    JOB_TERMINAL_STATUSES,
    apply_job_filters,
    serialize_job_detail,
    serialize_job_summary,
)

router = APIRouter(tags=["jobs"])


@router.get("/jobs")
def list_jobs(
    type: str | None = Query(default=None),
    workflow_key: str | None = Query(default=None),
    dataset_key: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    with Session(get_engine()) as session:
        stmt = apply_job_filters(
            select(JobRecord),
            job_type=type,
            workflow_key=workflow_key,
            dataset_key=dataset_key,
            status=status,
        )
        jobs = session.scalars(
            stmt.order_by(JobRecord.created_at.asc(), JobRecord.id.asc())
        ).all()
    return [serialize_job_summary(job) for job in jobs]


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    with Session(get_engine()) as session:
        job = session.get(JobRecord, job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return serialize_job_detail(job)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, response: Response) -> dict[str, Any]:
    """Cancel a job.

    A `queued` job is cancelled immediately (200). A `running` job records the
    request and is stopped at its runner's next cooperative checkpoint (202);
    the worker then marks it `cancelled`. Already-terminal jobs cannot be
    cancelled (409).
    """
    now = datetime.now(timezone.utc)
    with Session(get_engine()) as session:
        job = session.get(JobRecord, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        if job.status in JOB_TERMINAL_STATUSES:
            raise HTTPException(
                status_code=409, detail=f"job is already {job.status}; cannot cancel"
            )
        job.cancel_requested_at = now
        if job.status == "queued":
            # Never claimed — cancel cleanly here.
            job.status = "cancelled"
            job.finished_at = now
            job.error = "cancelled before start"
            response.status_code = status.HTTP_200_OK
        else:  # running — cooperative stop at the next checkpoint
            response.status_code = status.HTTP_202_ACCEPTED
        session.commit()
        session.refresh(job)
        return serialize_job_detail(job)
