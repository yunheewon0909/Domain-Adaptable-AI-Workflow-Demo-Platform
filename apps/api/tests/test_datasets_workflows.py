from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.config import get_settings
from api.db import get_engine
from api.main import app, get_embedding_client, get_llm_client
from api.llm import ChatResult
from api.models import JobRecord
from api.services.rag.ingest import ingest_documents
from api.services.workflows.service import execute_workflow


class FakeEmbeddingClient:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[float(text.lower().count("workflow")), float(text.lower().count("evidence"))] for text in texts]


class FakeWorkflowLLM:
    def __init__(self, response_text: str) -> None:
        self.response_text = response_text

    def generate_answer(self, *, question: str, context: str) -> ChatResult:
        return ChatResult(answer=self.response_text, model="fake-workflow-model", used_fallback=False)


def test_get_datasets_and_set_active_dataset(client: TestClient) -> None:
    response = client.get("/datasets")

    assert response.status_code == 200
    payload = response.json()
    assert [item["key"] for item in payload] == ["industrial_demo", "enterprise_docs"]
    assert any(item["is_active"] for item in payload)

    activate_response = client.post("/datasets/active", json={"dataset_key": "enterprise_docs"})

    assert activate_response.status_code == 200
    assert activate_response.json()["key"] == "enterprise_docs"
    assert activate_response.json()["is_active"] is True


def test_get_workflows_returns_exact_phase1_catalog(client: TestClient) -> None:
    response = client.get("/workflows")

    assert response.status_code == 200
    payload = response.json()
    assert [item["key"] for item in payload] == [
        "briefing",
        "recommendation",
        "report_generator",
    ]


def test_enqueue_workflow_job_and_filter_jobs(client: TestClient) -> None:
    response = client.post(
        "/workflows/briefing/jobs",
        json={
            "prompt": "Summarize the active dataset for a reviewer.",
            "dataset_key": "enterprise_docs",
            "k": 4,
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body == {
        "job_id": body["job_id"],
        "status": "queued",
        "workflow_key": "briefing",
        "dataset_key": "enterprise_docs",
    }

    with Session(get_engine()) as session:
        job = session.get(JobRecord, body["job_id"])

    assert job is not None
    assert job.type == "workflow_run"
    assert job.workflow_key == "briefing"
    assert job.dataset_key == "enterprise_docs"
    assert job.payload_json == {
        "workflow_key": "briefing",
        "dataset_key": "enterprise_docs",
        "prompt": "Summarize the active dataset for a reviewer.",
        "k": 4,
    }

    jobs_response = client.get(
        "/jobs",
        params={
            "workflow_key": "briefing",
            "dataset_key": "enterprise_docs",
            "status": "queued",
        },
    )
    assert jobs_response.status_code == 200
    assert jobs_response.json() == [
        {
            "id": body["job_id"],
            "type": "workflow_run",
            "workflow_key": "briefing",
            "dataset_key": "enterprise_docs",
            "status": "queued",
        }
    ]


def test_demo_route_serves_static_ui(client: TestClient) -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    assert "Domain-Adaptable AI Workflow Demo Platform" in response.text
    assert "dataset-select" in response.text


@pytest.mark.parametrize(
    ("workflow_key", "llm_output", "expected_field"),
    [
        (
            "briefing",
            '{"summary":"Short briefing","key_points":["Ground the answer in evidence"]}',
            "summary",
        ),
        (
            "recommendation",
            '{"recommendations":["Use a workflow catalog"],"rationale":"It keeps the demo repeatable."}',
            "recommendations",
        ),
        (
            "report_generator",
            '{"title":"Workflow Report","executive_summary":"Concise review","findings":["Evidence is visible"],"actions":["Run the next demo"]}',
            "title",
        ),
    ],
)
def test_execute_workflow_returns_typed_output_with_evidence(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    workflow_key: str,
    llm_output: str,
    expected_field: str,
) -> None:
    index_dir = tmp_path / "rag_index"
    rag_db_path = index_dir / "rag.db"
    source_dir = tmp_path / "sample_docs"
    source_dir.mkdir(parents=True)
    (source_dir / "brief.md").write_text(
        "workflow evidence panel should stay grounded in the retrieved dataset", encoding="utf-8"
    )

    ingest_documents(
        source_dir=source_dir,
        db_path=rag_db_path,
        chunk_size=120,
        chunk_overlap=20,
        embedding_client=FakeEmbeddingClient(),
    )

    monkeypatch.setenv("RAG_INDEX_DIR", str(index_dir))
    monkeypatch.setenv("RAG_DB_PATH", str(rag_db_path))
    monkeypatch.setenv("RAG_SOURCE_DIR", str(source_dir))
    get_settings.cache_clear()

    with Session(get_engine()) as session:
        result = execute_workflow(
            session=session,
            payload={
                "workflow_key": workflow_key,
                "dataset_key": "industrial_demo",
                "prompt": "Prepare a short briefing",
                "k": 3,
            },
            llm_client=FakeWorkflowLLM(llm_output),
            embedding_client=FakeEmbeddingClient(),
        )

    assert expected_field in result
    assert len(result["evidence"]) >= 1
    assert {"chunk_id", "source_path", "title", "text", "score"}.issubset(result["evidence"][0].keys())
