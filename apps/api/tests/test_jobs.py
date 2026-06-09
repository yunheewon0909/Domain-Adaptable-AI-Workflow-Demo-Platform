from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.db import get_engine
from api.models import JobRecord
from api.services.jobs import find_conflicting_job


def test_jobs_returns_empty_list_when_db_is_empty(client: TestClient) -> None:
    response = client.get("/jobs")

    assert response.status_code == 200
    assert response.json() == []


def test_jobs_returns_seeded_row(client: TestClient) -> None:
    with Session(get_engine()) as session:
        session.add(JobRecord(id="job-1", type="generic", status="queued"))
        session.commit()

    response = client.get("/jobs")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "job-1",
            "type": "generic",
            "workflow_key": None,
            "dataset_key": None,
            "status": "queued",
        }
    ]


def test_jobs_support_type_workflow_dataset_and_status_filters(
    client: TestClient,
) -> None:
    with Session(get_engine()) as session:
        session.add_all(
            [
                JobRecord(
                    id="job-1",
                    type="workflow_run",
                    workflow_key="briefing",
                    dataset_key="industrial_demo",
                    status="queued",
                ),
                JobRecord(
                    id="job-2",
                    type="workflow_run",
                    workflow_key="recommendation",
                    dataset_key="enterprise_docs",
                    status="queued",
                ),
                JobRecord(
                    id="job-3",
                    type="workflow_run",
                    workflow_key="briefing",
                    dataset_key="industrial_demo",
                    status="succeeded",
                ),
            ]
        )
        session.commit()

    response = client.get(
        "/jobs",
        params={
            "type": "workflow_run",
            "workflow_key": "briefing",
            "dataset_key": "industrial_demo",
            "status": "queued",
        },
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "job-1",
            "type": "workflow_run",
            "workflow_key": "briefing",
            "dataset_key": "industrial_demo",
            "status": "queued",
        }
    ]


def test_get_job_detail_returns_404_for_missing_job(client: TestClient) -> None:
    response = client.get("/jobs/missing")

    assert response.status_code == 404


def test_cancel_queued_job_returns_200_and_cancels(client: TestClient) -> None:
    with Session(get_engine()) as session:
        session.add(JobRecord(id="job-1", type="rag_index_collection", status="queued"))
        session.commit()

    response = client.post("/jobs/job-1/cancel")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["cancel_requested_at"] is not None
    assert body["finished_at"] is not None


def test_cancel_running_job_returns_202_and_sets_flag(client: TestClient) -> None:
    with Session(get_engine()) as session:
        session.add(JobRecord(id="job-1", type="rag_index_collection", status="running"))
        session.commit()

    response = client.post("/jobs/job-1/cancel")

    assert response.status_code == 202
    body = response.json()
    # Still running — the worker stops it at the next cooperative checkpoint.
    assert body["status"] == "running"
    assert body["cancel_requested_at"] is not None


def test_cancel_terminal_job_returns_409(client: TestClient) -> None:
    with Session(get_engine()) as session:
        session.add(JobRecord(id="job-1", type="rag_index_collection", status="succeeded"))
        session.commit()

    response = client.post("/jobs/job-1/cancel")

    assert response.status_code == 409


def test_cancel_missing_job_returns_404(client: TestClient) -> None:
    response = client.post("/jobs/missing/cancel")

    assert response.status_code == 404


def test_requeued_job_still_blocks_duplicate_enqueue(client: TestClient) -> None:
    # A requeued (status="queued") job is active, so find_conflicting_job blocks
    # a second enqueue of the same index job — no overlapping reindex.
    with Session(get_engine()) as session:
        session.add(
            JobRecord(
                id="job-1",
                type="rag_index_collection",
                status="queued",
                payload_json={"collection_id": "c1"},
                attempts=1,
                cancel_requested_at=None,
            )
        )
        session.commit()

    with Session(get_engine()) as session:
        conflict = find_conflicting_job(session, job_type="rag_index_collection")
        assert conflict is not None
        assert conflict.id == "job-1"
