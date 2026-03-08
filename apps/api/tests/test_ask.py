from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.config import get_settings
from api.main import app, get_embedding_client, get_llm_client
from api.llm import ChatResult, LLMClientError
from api.services.rag.ingest import ingest_documents


class FakeEmbeddingClient:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            normalized = text.lower()
            vectors.append(
                [
                    float(normalized.count("predictive") + normalized.count("maintenance")),
                    float(normalized.count("automation")),
                ]
            )
        return vectors


class FakeLLMClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def generate_answer(self, *, question: str, context: str) -> ChatResult:
        self.calls.append((question, context))
        return ChatResult(answer="mocked answer", model="fake-model", used_fallback=False)


class FailingLLMClient:
    def generate_answer(self, *, question: str, context: str) -> ChatResult:
        raise LLMClientError("simulated failure")


def test_ask_endpoint_returns_answer_sources_and_meta(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    index_dir = tmp_path / "rag_index"
    rag_db_path = index_dir / "rag.db"
    source_dir = tmp_path / "sample_docs"
    source_dir.mkdir(parents=True)
    (source_dir / "ops.md").write_text(
        "predictive maintenance for industrial automation", encoding="utf-8"
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
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434/v1")
    get_settings.cache_clear()

    fake_client = FakeLLMClient()
    app.dependency_overrides[get_llm_client] = lambda: fake_client
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()

    try:
        response = client.post("/ask", json={"question": "What does the doc say?", "k": 2})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200

    payload = response.json()
    assert payload["answer"] == "mocked answer"
    assert isinstance(payload["sources"], list)
    assert payload["sources"]
    assert {"chunk_id", "source_path", "title", "score", "text"}.issubset(
        payload["sources"][0].keys()
    )
    assert payload["meta"] == {
        "provider": "ollama",
        "model": "fake-model",
        "used_fallback": False,
        "retrieval_k": 2,
        "retrieved_count": len(payload["sources"]),
        "ollama_base_url": "http://ollama:11434/v1",
        "dataset_key": "industrial_demo",
        "dataset_title": "Industrial Operations Demo",
    }

    assert len(fake_client.calls) == 1
    asked_question, context = fake_client.calls[0]
    assert asked_question == "What does the doc say?"
    assert "predictive maintenance" in context


def test_ask_endpoint_requires_question_field(client: TestClient) -> None:
    response = client.post("/ask", json={"q": "missing required field"})

    assert response.status_code == 422


def test_ask_endpoint_without_index_returns_503(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RAG_INDEX_DIR", str(tmp_path / "missing-index"))
    monkeypatch.setenv("RAG_DB_PATH", str(tmp_path / "missing-index" / "rag.db"))
    get_settings.cache_clear()

    fake_client = FakeLLMClient()
    app.dependency_overrides[get_llm_client] = lambda: fake_client
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()

    try:
        response = client.post("/ask", json={"question": "hello"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert "rag-ingest" in response.json()["detail"]
    assert fake_client.calls == []


def test_ask_endpoint_maps_llm_failure_to_502(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    index_dir = tmp_path / "rag_index"
    rag_db_path = index_dir / "rag.db"
    source_dir = tmp_path / "sample_docs"
    source_dir.mkdir(parents=True)
    (source_dir / "ops.md").write_text("factory context", encoding="utf-8")

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

    app.dependency_overrides[get_llm_client] = lambda: FailingLLMClient()
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()

    try:
        response = client.post("/ask", json={"question": "hello"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
    assert response.json()["detail"] == "LLM request failed: simulated failure"


def test_ask_endpoint_validates_k_bounds(client: TestClient) -> None:
    response = client.post("/ask", json={"question": "hello", "k": 0})

    assert response.status_code == 422
