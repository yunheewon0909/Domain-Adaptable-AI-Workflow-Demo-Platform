from __future__ import annotations

import json
import math
from pathlib import Path

from api.config import get_settings
from api.services.rag.embedder import embed_text
from api.services.rag.embedding_client import (
    EmbeddingClient,
    EmbeddingClientError,
    OllamaEmbeddingClient,
)
from api.services.rag.sqlite_store import load_sqlite_chunks
from api.services.rag.types import QueryHit


class RAGIndexNotReadyError(FileNotFoundError):
    def __init__(self, *, db_path: Path, init_command: str) -> None:
        self.db_path = db_path
        self.init_command = init_command
        super().__init__(
            f"RAG index is not ready: {db_path}. Run {init_command} or enqueue RAG reindex before using retrieval-backed workflow."
        )


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _load_index_records(index_dir: Path) -> list[dict[str, object]]:
    index_file = index_dir / "index.json"
    if not index_file.exists():
        raise FileNotFoundError(
            f"RAG index file not found: {index_file}. Run `uv run --project apps/api rag-ingest` first."
        )

    payload = json.loads(index_file.read_text(encoding="utf-8"))
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError(
            f"Invalid index payload in {index_file}: 'records' must be a list"
        )

    return records


def _search_json_index(
    *, index_dir: Path, query_text: str, top_k: int
) -> list[QueryHit]:
    records = _load_index_records(index_dir)
    if not records:
        return []

    first_embedding = records[0].get("embedding")
    if not isinstance(first_embedding, list) or not first_embedding:
        raise ValueError("Invalid index payload: missing embedding vectors")

    query_embedding = embed_text(query_text, dimensions=len(first_embedding))
    hits: list[QueryHit] = []

    for record in records:
        embedding = record.get("embedding")
        chunk_id = record.get("chunk_id")
        source_path = record.get("source_path")
        text = record.get("text")
        if (
            not isinstance(embedding, list)
            or not isinstance(chunk_id, str)
            or not isinstance(source_path, str)
            or not isinstance(text, str)
        ):
            continue
        hits.append(
            QueryHit(
                chunk_id=chunk_id,
                source_path=source_path,
                text=text,
                score=_cosine(query_embedding, [float(value) for value in embedding]),
            )
        )

    hits.sort(key=lambda hit: hit.score, reverse=True)
    return hits[: max(1, top_k)]


def search_index(
    *,
    index_dir: Path,
    query_text: str,
    top_k: int = 3,
    db_path: Path | None = None,
    embedding_client: EmbeddingClient | None = None,
) -> list[QueryHit]:
    normalized_query = query_text.strip()
    if not normalized_query:
        raise ValueError("query_text must not be empty")

    resolved_db_path = db_path or (index_dir / "rag.db")
    if resolved_db_path.exists():
        chunks = load_sqlite_chunks(resolved_db_path)
        if not chunks:
            return []

        if embedding_client is None:
            settings = get_settings()
            embedding_client = OllamaEmbeddingClient(
                base_url=settings.ollama_embed_base_url,
                model=settings.ollama_embed_model,
                timeout_seconds=settings.ollama_timeout_seconds,
            )

        try:
            query_embedding = embedding_client.embed_texts([normalized_query])[0]
        except (EmbeddingClientError, IndexError) as exc:
            raise ValueError(f"Failed to generate query embedding: {exc}") from exc

        hits = [
            QueryHit(
                chunk_id=chunk.chunk_id,
                source_path=chunk.source_path,
                text=chunk.text,
                score=_cosine(query_embedding, chunk.embedding),
            )
            for chunk in chunks
        ]
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[: max(1, top_k)]

    if (index_dir / "index.json").exists():
        return _search_json_index(
            index_dir=index_dir, query_text=normalized_query, top_k=top_k
        )

    raise RAGIndexNotReadyError(
        db_path=resolved_db_path,
        init_command="`uv run --project apps/api rag-ingest`",
    )
