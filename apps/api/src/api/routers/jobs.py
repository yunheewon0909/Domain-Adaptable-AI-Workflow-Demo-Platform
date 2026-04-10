from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.db import get_engine
from api.models import JobRecord
from api.services.jobs import (
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
    plc_suite_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    with Session(get_engine()) as session:
        stmt = apply_job_filters(
            select(JobRecord),
            job_type=type,
            workflow_key=workflow_key,
            dataset_key=dataset_key,
            plc_suite_id=plc_suite_id,
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
