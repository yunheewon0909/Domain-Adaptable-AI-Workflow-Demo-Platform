from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.config import get_settings
from api.db import Base, get_engine
from api.main import app, get_embedding_client, get_llm_client
from api.llm import ChatResult
from api.models import JobRecord, ModelRegistryRecord
from api.services.rag.ingest import ingest_documents
from api.services.workflows.service import execute_workflow


class FakeEmbeddingClient:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [
            [
                float(text.lower().count("workflow")),
                float(text.lower().count("evidence")),
            ]
            for text in texts
        ]


class FakeWorkflowLLM:
    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.calls: list[dict[str, object | None]] = []

    def generate_answer(
        self,
        *,
        question: str,
        context: str,
        model: str | None = None,
        temperature: float = 0,
        max_tokens: int | None = None,
    ) -> ChatResult:
        self.calls.append(
            {
                "question": question,
                "context": context,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return ChatResult(
            answer=self.response_text,
            model=model or "fake-workflow-model",
            used_fallback=False,
        )


def test_get_datasets_and_set_active_dataset(client: TestClient) -> None:
    response = client.get("/datasets")

    assert response.status_code == 200
    payload = response.json()
    assert [item["key"] for item in payload] == ["industrial_demo", "enterprise_docs"]
    assert any(item["is_active"] for item in payload)

    activate_response = client.post(
        "/datasets/active", json={"dataset_key": "enterprise_docs"}
    )

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
    assert job.max_attempts == 1

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
            "plc_suite_id": None,
            "status": "queued",
        }
    ]


def test_enqueue_workflow_job_accepts_rag_collection_and_model_selection(
    client: TestClient,
) -> None:
    collection_response = client.post(
        "/rag-collections",
        json={"name": "Workflow docs", "description": "Reviewer workflow context"},
    )
    assert collection_response.status_code == 201
    collection_id = collection_response.json()["id"]

    model_response = client.get("/models")
    assert model_response.status_code == 200
    model_id = model_response.json()[0]["id"]

    response = client.post(
        "/workflows/briefing/jobs",
        json={
            "prompt": "Summarize the selected workflow collection.",
            "rag_collection_id": collection_id,
            "model_id": model_id,
            "k": 3,
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body == {
        "job_id": body["job_id"],
        "status": "queued",
        "workflow_key": "briefing",
        "dataset_key": None,
        "rag_collection_id": collection_id,
        "model_id": model_id,
    }

    with Session(get_engine()) as session:
        job = session.get(JobRecord, body["job_id"])

    assert job is not None
    assert job.payload_json == {
        "workflow_key": "briefing",
        "prompt": "Summarize the selected workflow collection.",
        "rag_collection_id": collection_id,
        "model_id": model_id,
        "k": 3,
    }


def test_enqueue_workflow_job_rejects_artifact_only_model_selection(
    client: TestClient,
) -> None:
    with Session(get_engine()) as session:
        session.add(
            ModelRegistryRecord(
                id="model-artifact-only",
                display_name="Artifact-only reviewer model",
                source_type="fine_tuned",
                base_model_name="qwen2.5:3b-instruct-q4_K_M",
                ollama_model_name="artifact::ft-job-1",
                published_model_name=None,
                artifact_id=None,
                status="artifact_ready",
                publish_status="publish_ready",
                tags_json=["fine_tuned"],
                description="Not selectable for runtime inference.",
                updated_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

    response = client.post(
        "/workflows/briefing/jobs",
        json={
            "prompt": "Summarize the active dataset for a reviewer.",
            "dataset_key": "enterprise_docs",
            "model_id": "model-artifact-only",
            "k": 4,
        },
    )

    assert response.status_code == 404
    assert any(
        fragment in response.json()["detail"]
        for fragment in (
            "artifact",
            "serving model",
            "publish manifest",
        )
    )


def test_demo_route_serves_static_ui(client: TestClient) -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    assert "Domain-Adaptable AI Workflow Demo API" in response.text
    assert "workflow-source-select" in response.text
    assert "workflow-model-select" in response.text


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
        "workflow evidence panel should stay grounded in the retrieved dataset",
        encoding="utf-8",
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

    llm = FakeWorkflowLLM(llm_output)

    with Session(get_engine()) as session:
        result = execute_workflow(
            session=session,
            payload={
                "workflow_key": workflow_key,
                "dataset_key": "industrial_demo",
                "prompt": "Prepare a short briefing",
                "k": 3,
            },
            llm_client=llm,
            embedding_client=FakeEmbeddingClient(),
        )

    assert expected_field in result
    assert len(result["evidence"]) >= 1
    assert llm.calls[-1]["max_tokens"] == 512
    assert {"chunk_id", "source_path", "title", "text", "score"}.issubset(
        result["evidence"][0].keys()
    )


def test_execute_workflow_supports_rag_collection_source_and_model_metadata(
    client: TestClient,
) -> None:
    collection_response = client.post(
        "/rag-collections",
        json={"name": "Workflow docs", "description": "Reviewer workflow context"},
    )
    assert collection_response.status_code == 201
    collection_id = collection_response.json()["id"]

    upload_response = client.post(
        f"/rag-collections/{collection_id}/documents",
        files={
            "file": (
                "workflow-notes.md",
                b"workflow reviewer evidence should stay grounded in collection context",
                "text/markdown",
            )
        },
    )
    assert upload_response.status_code == 201

    model_response = client.get("/models")
    assert model_response.status_code == 200
    selected_model = model_response.json()[0]

    llm = FakeWorkflowLLM(
        '{"summary":"Collection grounded briefing","key_points":["Use collection evidence"]}'
    )

    with Session(get_engine()) as session:
        result = execute_workflow(
            session=session,
            payload={
                "workflow_key": "briefing",
                "prompt": "Prepare a collection-backed briefing",
                "rag_collection_id": collection_id,
                "model_id": selected_model["id"],
                "k": 3,
            },
            llm_client=llm,
            embedding_client=FakeEmbeddingClient(),
        )

    assert result["summary"] == "Collection grounded briefing"
    assert len(result["evidence"]) == 1
    assert result["evidence"][0]["source_path"] == "workflow-notes.md"
    assert result["meta"]["source_type"] == "rag_collection"
    assert result["meta"]["source_id"] == collection_id
    assert result["meta"]["source_label"] == "Workflow docs"
    assert result["meta"]["rag_collection_id"] == collection_id
    assert result["meta"]["model_id"] == selected_model["id"]
    assert result["meta"]["model_display_name"] == selected_model["display_name"]
    assert result["meta"]["selected_model"] == selected_model["serving_model_name"]
    assert result["meta"]["used_fallback"] is False
    assert llm.calls[-1]["model"] == selected_model["serving_model_name"]


@pytest.mark.parametrize(
    ("filename", "content", "query", "expected_status"),
    [
        (None, None, "Prepare a reviewer briefing", "empty"),
        ("workflow-notes.md", b"totally unrelated source text", "workflow evidence", "no_match"),
    ],
)
def test_execute_workflow_handles_collection_without_matching_context_gracefully(
    client: TestClient,
    filename: str | None,
    content: bytes | None,
    query: str,
    expected_status: str,
) -> None:
    collection_response = client.post(
        "/rag-collections",
        json={"name": "Workflow docs", "description": "Reviewer workflow context"},
    )
    assert collection_response.status_code == 201
    collection_id = collection_response.json()["id"]

    if filename is not None and content is not None:
        upload_response = client.post(
            f"/rag-collections/{collection_id}/documents",
            files={"file": (filename, content, "text/markdown")},
        )
        assert upload_response.status_code == 201

    llm = FakeWorkflowLLM('{"summary":"unused","key_points":["unused"]}')

    with Session(get_engine()) as session:
        result = execute_workflow(
            session=session,
            payload={
                "workflow_key": "briefing",
                "prompt": query,
                "rag_collection_id": collection_id,
                "k": 3,
            },
            llm_client=llm,
            embedding_client=FakeEmbeddingClient(),
        )

    assert result["evidence"] == []
    assert result["meta"]["degraded"] is True
    assert result["meta"]["rag_status"] == expected_status
    assert result["meta"]["source_type"] == "rag_collection"
    assert result["meta"]["rag_collection_id"] == collection_id
    assert llm.calls == []


def test_execute_workflow_returns_guidance_when_rag_index_is_not_ready(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    index_dir = tmp_path / "rag_index"
    source_dir = tmp_path / "sample_docs"
    source_dir.mkdir(parents=True)
    (source_dir / "brief.md").write_text("workflow evidence source", encoding="utf-8")

    monkeypatch.setenv("RAG_INDEX_DIR", str(index_dir))
    monkeypatch.setenv("RAG_DB_PATH", str(index_dir / "rag.db"))
    monkeypatch.setenv("RAG_SOURCE_DIR", str(source_dir))
    get_settings.cache_clear()

    llm = FakeWorkflowLLM('{"summary":"unused","key_points":["unused"]}')

    with Session(get_engine()) as session:
        result = execute_workflow(
            session=session,
            payload={
                "workflow_key": "briefing",
                "dataset_key": "industrial_demo",
                "prompt": "Prepare a short briefing",
                "k": 3,
            },
            llm_client=llm,
            embedding_client=FakeEmbeddingClient(),
        )

    assert result["meta"]["rag_status"] == "not_ready"
    assert result["meta"]["degraded"] is True
    assert result["meta"]["db_path"] == str(index_dir / "rag.db")
    assert result["meta"]["source_type"] == "dataset"
    assert result["meta"]["source_id"] == "industrial_demo"
    assert result["evidence"] == []
    assert "RAG index is not ready" in result["key_points"]
    assert any(
        "Run rag-ingest or enqueue RAG reindex" in item for item in result["key_points"]
    )
    assert any(
        "docker compose exec -T api uv run rag-ingest" in item
        for item in result["key_points"]
    )
    assert llm.calls == []


def test_execute_workflow_normalizes_report_generator_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sqlite_db_path = tmp_path / "workflow-tests.db"
    index_dir = tmp_path / "rag_index"
    rag_db_path = index_dir / "rag.db"
    source_dir = tmp_path / "sample_docs"
    source_dir.mkdir(parents=True)
    (source_dir / "report.md").write_text(
        "Reviewer evidence should stay grounded in the retrieved dataset.",
        encoding="utf-8",
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
    monkeypatch.setenv("API_DATABASE_URL", f"sqlite+pysqlite:///{sqlite_db_path}")
    get_settings.cache_clear()
    get_engine.cache_clear()

    engine = get_engine()
    Base.metadata.create_all(bind=engine)

    malformed_output = (
        '{"title":"Workflow Report","executive_summary":"Concise review",'
        '"findings":[],"actions":[{"action":"Create a grounded reviewer report"}]}'
    )

    with Session(get_engine()) as session:
        result = execute_workflow(
            session=session,
            payload={
                "workflow_key": "report_generator",
                "dataset_key": "industrial_demo",
                "prompt": "Prepare a short report",
                "k": 3,
            },
            llm_client=FakeWorkflowLLM(malformed_output),
            embedding_client=FakeEmbeddingClient(),
        )

    assert result["title"] == "Workflow Report"
    assert result["actions"] == ["Create a grounded reviewer report"]
    assert len(result["findings"]) >= 1
    assert all(isinstance(item, str) and item for item in result["findings"])
    assert len(result["evidence"]) >= 1

    engine.dispose()
