from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.db import get_engine
from api.models import JobRecord
from api.services.jobs import (
    apply_job_filters,
    create_job,
    serialize_job_detail,
    serialize_job_summary,
)
from api.services.plc import (
    build_normalization_suggestion,
    create_plc_job_payload,
    flatten_cases,
    get_plc_suite_detail,
    import_plc_suite,
    list_plc_suites,
)
from api.services.plc.service import PLCImportError

router = APIRouter(tags=["plc"])


class PLCTestRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite_id: str | None = None
    testcase_ids: list[str] = Field(default_factory=list)
    target_key: str = Field(default="stub-local", min_length=1)


class PLLMSuggestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_row: dict[str, Any]


@router.post("/plc-testcases/import", status_code=201)
async def import_plc_testcases(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
) -> dict[str, Any]:
    file_bytes = await file.read()
    with Session(get_engine()) as session:
        try:
            suite, imported_count, rejected_count = import_plc_suite(
                session,
                filename=file.filename or "uploaded.csv",
                file_bytes=file_bytes,
                title=title,
            )
        except PLCImportError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "suite_id": suite.id,
        "title": suite.title,
        "imported_count": imported_count,
        "rejected_count": rejected_count,
    }


@router.get("/plc-test-suites")
def get_plc_test_suites() -> list[dict[str, Any]]:
    with Session(get_engine()) as session:
        return [suite.model_dump(mode="json") for suite in list_plc_suites(session)]


@router.get("/plc-test-suites/{suite_id}")
def get_plc_test_suite(suite_id: str) -> dict[str, Any]:
    with Session(get_engine()) as session:
        suite = get_plc_suite_detail(session, suite_id)
    if suite is None:
        raise HTTPException(status_code=404, detail="PLC suite not found")
    return suite.model_dump(mode="json")


@router.get("/plc-testcases")
def get_plc_testcases(
    instruction: str | None = Query(default=None),
    input_type: str | None = Query(default=None),
    suite_id: str | None = Query(default=None),
    tag: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    with Session(get_engine()) as session:
        return flatten_cases(
            session,
            instruction_name=instruction,
            input_type=input_type,
            suite_id=suite_id,
            tag=tag,
        )


@router.get("/plc-testcases/{testcase_id}")
def get_plc_testcase(testcase_id: str) -> dict[str, Any]:
    suite_id = testcase_id.split("::", 1)[0]
    with Session(get_engine()) as session:
        cases = flatten_cases(session, suite_id=suite_id)
    for case in cases:
        if case["id"] == testcase_id:
            return case
    raise HTTPException(status_code=404, detail="PLC testcase not found")


@router.post("/plc-test-runs", status_code=202)
def enqueue_plc_test_run(request: PLCTestRunRequest) -> dict[str, Any]:
    with Session(get_engine()) as session:
        try:
            suite, payload = create_plc_job_payload(
                session,
                suite_id=request.suite_id,
                testcase_ids=request.testcase_ids,
                target_key=request.target_key,
            )
        except PLCImportError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        job = create_job(
            session,
            job_type="plc_test_run",
            payload_json=payload,
            plc_suite_id=suite.id,
        )
    return {
        "job_id": job.id,
        "status": job.status,
        "type": job.type,
        "plc_suite_id": suite.id,
        "suite_title": suite.title,
        "target_key": request.target_key,
    }


def _serialize_plc_run(job: JobRecord) -> dict[str, Any]:
    detail = serialize_job_detail(job)
    result_json = detail.get("result_json") or {}
    if isinstance(result_json, dict):
        detail["summary"] = {
            "total_count": result_json.get("total_count", 0),
            "passed_count": result_json.get("passed_count", 0),
            "failed_count": result_json.get("failed_count", 0),
            "error_count": result_json.get("error_count", 0),
        }
    return detail


@router.get("/plc-test-runs")
def list_plc_test_runs(
    suite_id: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    with Session(get_engine()) as session:
        stmt = apply_job_filters(
            select(JobRecord),
            job_type="plc_test_run",
            plc_suite_id=suite_id,
        )
        jobs = session.scalars(
            stmt.order_by(JobRecord.created_at.desc(), JobRecord.id.desc())
        ).all()
    return [_serialize_plc_run(job) for job in jobs]


@router.get("/plc-test-runs/{run_id}")
def get_plc_test_run(run_id: str) -> dict[str, Any]:
    with Session(get_engine()) as session:
        job = session.get(JobRecord, run_id)
    if job is None or job.type != "plc_test_run":
        raise HTTPException(status_code=404, detail="PLC test run not found")
    return _serialize_plc_run(job)


@router.get("/plc-test-runs/{run_id}/items")
def list_plc_test_run_items(run_id: str) -> list[dict[str, Any]]:
    with Session(get_engine()) as session:
        job = session.get(JobRecord, run_id)
    if job is None or job.type != "plc_test_run":
        raise HTTPException(status_code=404, detail="PLC test run not found")
    result_json = serialize_job_detail(job).get("result_json") or {}
    if not isinstance(result_json, dict):
        return []
    items = result_json.get("items")
    return items if isinstance(items, list) else []


@router.get("/plc-test-runs/{run_id}/items/{item_id}")
def get_plc_test_run_item(run_id: str, item_id: str) -> dict[str, Any]:
    items = list_plc_test_run_items(run_id)
    for item in items:
        if item.get("id") == item_id:
            return item
    raise HTTPException(status_code=404, detail="PLC test run item not found")


@router.get("/plc-dashboard/summary")
def get_plc_dashboard_summary() -> dict[str, Any]:
    with Session(get_engine()) as session:
        jobs = session.scalars(
            apply_job_filters(select(JobRecord), job_type="plc_test_run").order_by(
                JobRecord.created_at.desc(), JobRecord.id.desc()
            )
        ).all()
        suites = list_plc_suites(session)
    status_counts = Counter(job.status for job in jobs)
    failure_hotspots: Counter[str] = Counter()
    recent_runs: list[dict[str, Any]] = []
    for job in jobs[:5]:
        detail = _serialize_plc_run(job)
        recent_runs.append(
            {
                "id": detail["id"],
                "status": detail["status"],
                "plc_suite_id": detail["plc_suite_id"],
                "summary": detail.get("summary", {}),
                "created_at": detail.get("created_at"),
            }
        )
        result_json = detail.get("result_json") or {}
        if isinstance(result_json, dict):
            for item in result_json.get("items", []):
                if item.get("status") in {"failed", "error"}:
                    failure_hotspots[str(item.get("case_key"))] += 1
    return {
        "suite_count": len(suites),
        "run_count": len(jobs),
        "queue_stats": {
            "queued": status_counts.get("queued", 0),
            "running": status_counts.get("running", 0),
            "succeeded": status_counts.get("succeeded", 0),
            "failed": status_counts.get("failed", 0),
        },
        "recent_runs": recent_runs,
        "failure_hotspots": [
            {"case_key": case_key, "count": count}
            for case_key, count in failure_hotspots.most_common(5)
        ],
    }


@router.post("/plc-llm/suggest-testcase-normalization")
def suggest_plc_testcase_normalization(
    request: PLLMSuggestionRequest,
) -> dict[str, Any]:
    return build_normalization_suggestion(request.raw_row)
