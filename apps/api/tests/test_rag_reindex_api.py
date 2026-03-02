from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.db import get_engine
from api.models import JobRecord


def test_enqueue_rag_reindex_creates_queued_job(client: TestClient) -> None:
    response = client.post("/rag/reindex")

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert isinstance(body["job_id"], str)

    with Session(get_engine()) as session:
        job = session.get(JobRecord, body["job_id"])

    assert job is not None
    assert job.type == "rag_reindex"
    assert job.status == "queued"
    assert job.payload_json is None


def test_enqueue_rag_reindex_accepts_payload_json(client: TestClient) -> None:
    response = client.post("/rag/reindex", json={"payload_json": {"requested_by": "test"}})

    assert response.status_code == 202
    body = response.json()

    with Session(get_engine()) as session:
        job = session.get(JobRecord, body["job_id"])

    assert job is not None
    assert job.payload_json == {"requested_by": "test"}


def test_enqueue_rag_reindex_returns_conflict_when_active_job_exists(client: TestClient) -> None:
    with Session(get_engine()) as session:
        session.add(JobRecord(id="11", type="rag_reindex", status="running"))
        session.commit()

    response = client.post("/rag/reindex")

    assert response.status_code == 409
    assert response.json() == {
        "detail": "rag_reindex already queued/running",
        "existing_job_id": "11",
    }


def test_get_job_detail_returns_job_payload(client: TestClient) -> None:
    with Session(get_engine()) as session:
        session.add(
            JobRecord(
                id="22",
                type="rag_reindex",
                status="succeeded",
                attempts=1,
                max_attempts=3,
                payload_json={"trigger": "manual"},
                result_json={"chunks": 5},
            )
        )
        session.commit()

    response = client.get("/jobs/22")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "22"
    assert body["type"] == "rag_reindex"
    assert body["status"] == "succeeded"
    assert body["payload_json"] == {"trigger": "manual"}
    assert body["result_json"] == {"chunks": 5}


def test_enqueue_rag_warmup_creates_queued_job(client: TestClient) -> None:
    response = client.post("/rag/warmup")

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert isinstance(body["job_id"], str)

    with Session(get_engine()) as session:
        job = session.get(JobRecord, body["job_id"])

    assert job is not None
    assert job.type == "ollama_warmup"
    assert job.status == "queued"


def test_enqueue_rag_warmup_returns_conflict_when_active_job_exists(client: TestClient) -> None:
    with Session(get_engine()) as session:
        session.add(JobRecord(id="31", type="ollama_warmup", status="running"))
        session.commit()

    response = client.post("/rag/warmup")

    assert response.status_code == 409
    assert response.json() == {
        "detail": "ollama_warmup already queued/running",
        "existing_job_id": "31",
    }


def test_enqueue_rag_verify_creates_queued_job(client: TestClient) -> None:
    response = client.post("/rag/verify")

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert isinstance(body["job_id"], str)

    with Session(get_engine()) as session:
        job = session.get(JobRecord, body["job_id"])

    assert job is not None
    assert job.type == "rag_verify_index"
    assert job.status == "queued"


def test_enqueue_rag_verify_returns_conflict_when_active_job_exists(client: TestClient) -> None:
    with Session(get_engine()) as session:
        session.add(JobRecord(id="41", type="rag_verify_index", status="queued"))
        session.commit()

    response = client.post("/rag/verify")

    assert response.status_code == 409
    assert response.json() == {
        "detail": "rag_verify_index already queued/running",
        "existing_job_id": "41",
    }
