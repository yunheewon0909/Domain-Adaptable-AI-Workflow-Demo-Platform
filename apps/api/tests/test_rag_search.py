from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.config import get_settings
from api.db import Base, get_engine
from api.main import app, get_embedding_client
from api.models import JobRecord
from api.services.rag.chunker import chunk_documents
from api.services.rag.embedder import embed_chunks
from api.services.rag.index_store import persist_index
from api.services.rag.ingest import ingest_documents
from api.services.rag.loader import load_documents
from api.services.rag.query import search_index


class FakeEmbeddingClient:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            normalized = text.lower()
            vectors.append(
                [
                    float(normalized.count("automation") + normalized.count("robotics")),
                    float(normalized.count("finance") + normalized.count("accounting")),
                ]
            )
        return vectors


@pytest.fixture
def rag_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[tuple[TestClient, Path]]:
    sqlite_db_path = tmp_path / "api-tests.db"
    index_dir = tmp_path / "rag_index"
    rag_db_path = index_dir / "rag.db"

    monkeypatch.setenv("API_DATABASE_URL", f"sqlite+pysqlite:///{sqlite_db_path}")
    monkeypatch.setenv("API_DB_ECHO", "false")
    monkeypatch.setenv("RAG_INDEX_DIR", str(index_dir))
    monkeypatch.setenv("RAG_DB_PATH", str(rag_db_path))
    monkeypatch.setenv("RAG_SOURCE_DIR", str(tmp_path / "sample_docs"))

    get_settings.cache_clear()
    get_engine.cache_clear()

    engine = get_engine()
    Base.metadata.create_all(bind=engine)

    with Session(engine) as session:
        session.add(JobRecord(id="seed-job", status="queued"))
        session.commit()

    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    with TestClient(app) as client:
        yield client, index_dir
    app.dependency_overrides.clear()

    engine.dispose()


def test_search_index_returns_ranked_hits(tmp_path: Path) -> None:
    source_dir = tmp_path / "sample_docs"
    source_dir.mkdir(parents=True)
    (source_dir / "robotics.txt").write_text(
        "robotics automation assembly line maintenance", encoding="utf-8"
    )
    (source_dir / "finance.txt").write_text(
        "financial forecast revenue accounting", encoding="utf-8"
    )

    rag_db_path = tmp_path / "rag_index" / "rag.db"
    ingest_documents(
        source_dir=source_dir,
        db_path=rag_db_path,
        chunk_size=120,
        chunk_overlap=20,
        embedding_client=FakeEmbeddingClient(),
    )

    hits = search_index(
        index_dir=tmp_path / "rag_index",
        db_path=rag_db_path,
        query_text="automation robotics",
        top_k=1,
        embedding_client=FakeEmbeddingClient(),
    )

    assert len(hits) == 1
    assert hits[0].source_path == "robotics.txt"


def test_rag_search_endpoint_returns_hits(rag_client: tuple[TestClient, Path], tmp_path: Path) -> None:
    client, index_dir = rag_client

    source_dir = tmp_path / "sample_docs"
    source_dir.mkdir(parents=True)
    (source_dir / "ops.md").write_text(
        "predictive maintenance and automation for factories", encoding="utf-8"
    )

    ingest_documents(
        source_dir=source_dir,
        db_path=index_dir / "rag.db",
        chunk_size=120,
        chunk_overlap=20,
        embedding_client=FakeEmbeddingClient(),
    )

    get_settings.cache_clear()

    response = client.get("/rag/search", params={"q": "maintenance automation", "k": 2})

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert len(payload) >= 1
    assert {"chunk_id", "source_path", "title", "score", "text"}.issubset(payload[0].keys())


def test_rag_search_endpoint_without_index_returns_503(
    rag_client: tuple[TestClient, Path],
) -> None:
    client, _ = rag_client

    response = client.get("/rag/search", params={"q": "hello", "k": 2})

    assert response.status_code == 503
    assert "rag-ingest" in response.json()["detail"]


def test_search_index_falls_back_to_json_when_sqlite_missing(tmp_path: Path) -> None:
    source_dir = tmp_path / "sample_docs"
    source_dir.mkdir(parents=True)
    (source_dir / "legacy.txt").write_text("legacy json index compatibility path", encoding="utf-8")

    documents = load_documents(source_dir)
    chunks = chunk_documents(documents, chunk_size=120, chunk_overlap=20)
    embeddings = embed_chunks(chunks, dimensions=16)
    index_dir = tmp_path / "rag_index"
    persist_index(index_dir, chunks=chunks, embeddings=embeddings)

    hits = search_index(
        index_dir=index_dir,
        db_path=index_dir / "rag.db",
        query_text="legacy compatibility",
        top_k=1,
        embedding_client=FakeEmbeddingClient(),
    )

    assert len(hits) == 1
    assert hits[0].source_path == "legacy.txt"
