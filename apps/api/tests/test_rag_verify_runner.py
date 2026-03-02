from array import array
from pathlib import Path
import sqlite3

import pytest

from api.services.rag.verify_index_job_runner import run_verify_index_job


class FakeEmbeddingClient:
    def __init__(self, dimensions: int) -> None:
        self._dimensions = dimensions

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] * self._dimensions for _ in texts]


def _embedding_blob(dimensions: int) -> bytes:
    values = array("f", [1.0] * dimensions)
    return values.tobytes()


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE documents (
            id TEXT PRIMARY KEY,
            source_path TEXT NOT NULL UNIQUE,
            content_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE chunks (
            id TEXT PRIMARY KEY,
            doc_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            embedding BLOB NOT NULL,
            embedding_dim INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def _create_valid_db(db_path: Path, *, embedding_dim: int = 3) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        _create_schema(connection)
        connection.execute(
            "INSERT INTO documents (id, source_path, content_hash) VALUES (?, ?, ?)",
            ("doc-1", "doc.txt", "abc123"),
        )
        connection.execute(
            """
            INSERT INTO chunks (id, doc_id, chunk_index, text, embedding, embedding_dim)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "doc-1-0000",
                "doc-1",
                0,
                "maintenance automation check",
                sqlite3.Binary(_embedding_blob(embedding_dim)),
                embedding_dim,
            ),
        )


def test_run_verify_index_job_success(tmp_path: Path) -> None:
    db_path = tmp_path / "rag_index" / "rag.db"
    _create_valid_db(db_path, embedding_dim=3)

    result = run_verify_index_job(
        db_path=db_path,
        index_dir=db_path.parent,
        expected_embed_dim=3,
        sample_query="maintenance automation",
        embedding_client=FakeEmbeddingClient(dimensions=3),
    )

    assert result["db_path"] == str(db_path)
    assert result["documents"] == 1
    assert result["chunks"] == 1
    assert result["min_embedding_dim"] == 3
    assert result["max_embedding_dim"] == 3
    assert result["distinct_embedding_dims"] == [3]
    assert result["expected_embedding_dim"] == 3
    assert result["sample_query_hits"] >= 1


def test_run_verify_index_job_fails_when_chunks_are_empty(tmp_path: Path) -> None:
    db_path = tmp_path / "rag_index" / "rag.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as connection:
        _create_schema(connection)
        connection.execute(
            "INSERT INTO documents (id, source_path, content_hash) VALUES (?, ?, ?)",
            ("doc-1", "doc.txt", "abc123"),
        )

    with pytest.raises(ValueError, match="chunks count is zero"):
        run_verify_index_job(
            db_path=db_path,
            index_dir=db_path.parent,
            expected_embed_dim=3,
            sample_query="maintenance automation",
            embedding_client=FakeEmbeddingClient(dimensions=3),
        )


def test_run_verify_index_job_fails_when_dim_mismatch(tmp_path: Path) -> None:
    db_path = tmp_path / "rag_index" / "rag.db"
    _create_valid_db(db_path, embedding_dim=3)

    with pytest.raises(ValueError, match="embedding_dim mismatch"):
        run_verify_index_job(
            db_path=db_path,
            index_dir=db_path.parent,
            expected_embed_dim=768,
            sample_query="maintenance automation",
            embedding_client=FakeEmbeddingClient(dimensions=3),
        )


def test_run_verify_index_job_fails_when_required_tables_missing(tmp_path: Path) -> None:
    db_path = tmp_path / "rag_index" / "rag.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE documents (id TEXT PRIMARY KEY)")

    with pytest.raises(ValueError, match="missing required tables"):
        run_verify_index_job(
            db_path=db_path,
            index_dir=db_path.parent,
            expected_embed_dim=0,
            sample_query="",
            embedding_client=FakeEmbeddingClient(dimensions=3),
        )
