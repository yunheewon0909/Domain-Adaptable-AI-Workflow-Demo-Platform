from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any, TypedDict

from api.config import get_settings
from api.services.rag.embedding_client import EmbeddingClient, OllamaEmbeddingClient
from api.services.rag.query import search_index


class VerifyIndexResult(TypedDict):
    db_path: str
    documents: int
    chunks: int
    min_embedding_dim: int
    max_embedding_dim: int
    distinct_embedding_dims: list[int]
    expected_embedding_dim: int
    sample_query: str
    sample_query_hits: int


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rag-verify-index-runner",
        description="Validate rag.db structure/content and run a retrieval sanity check",
    )
    parser.add_argument(
        "--payload-json",
        default=None,
        help="Optional JSON object payload with runtime overrides (db_path/index_dir/expected_embed_dim/sample_query)",
    )
    return parser


def _resolve_payload(payload_json_raw: str | None) -> dict[str, object]:
    if payload_json_raw is None:
        return {}
    parsed = json.loads(payload_json_raw)
    if not isinstance(parsed, dict):
        raise ValueError("payload_json must be a JSON object")
    return parsed


def _payload_int(payload: dict[str, object], key: str, default: int, *, minimum: int = 0) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    if isinstance(value, int):
        return max(minimum, value)
    if isinstance(value, str):
        return max(minimum, int(value))
    raise ValueError(f"{key} must be an integer")


def _read_required_tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {str(row[0]) for row in rows if row and row[0]}


def _read_int(connection: sqlite3.Connection, query: str) -> int:
    row = connection.execute(query).fetchone()
    return int(row[0]) if row is not None and row[0] is not None else 0


def _validate_sqlite(db_path: Path, *, expected_embed_dim: int) -> tuple[int, int, list[int]]:
    with sqlite3.connect(db_path) as connection:
        tables = _read_required_tables(connection)
        required_tables = {"documents", "chunks"}
        missing = sorted(required_tables - tables)
        if missing:
            raise ValueError(f"verify failed: missing required tables: {', '.join(missing)}")

        documents_count = _read_int(connection, "SELECT COUNT(*) FROM documents")
        chunks_count = _read_int(connection, "SELECT COUNT(*) FROM chunks")
        if chunks_count <= 0:
            raise ValueError("verify failed: chunks count is zero")

        invalid_dim_rows = _read_int(connection, "SELECT COUNT(*) FROM chunks WHERE embedding_dim <= 0")
        if invalid_dim_rows > 0:
            raise ValueError("verify failed: chunks contain non-positive embedding_dim")

        dim_rows = connection.execute(
            "SELECT DISTINCT embedding_dim FROM chunks ORDER BY embedding_dim"
        ).fetchall()

    dims = [int(row[0]) for row in dim_rows if row and row[0] is not None]
    if not dims:
        raise ValueError("verify failed: no embedding_dim values found")

    if expected_embed_dim > 0 and any(dim != expected_embed_dim for dim in dims):
        raise ValueError(
            f"verify failed: embedding_dim mismatch expected={expected_embed_dim} observed={dims}"
        )

    return documents_count, chunks_count, dims


def _run_sample_query(
    *,
    sample_query: str,
    index_dir: Path,
    db_path: Path,
    embedding_client: EmbeddingClient,
) -> int:
    normalized_query = sample_query.strip()
    if not normalized_query:
        return 0

    hits = search_index(
        index_dir=index_dir,
        db_path=db_path,
        query_text=normalized_query,
        top_k=1,
        embedding_client=embedding_client,
    )
    hit_count = len(hits)
    if hit_count <= 0:
        raise ValueError("verify failed: sample query returned zero results")
    return hit_count


def run_verify_index_job(
    *,
    db_path: Path,
    index_dir: Path,
    expected_embed_dim: int,
    sample_query: str,
    embedding_client: EmbeddingClient,
) -> VerifyIndexResult:
    if not db_path.exists():
        raise FileNotFoundError(
            f"verify failed: rag db not found at {db_path}. Run reindex first."
        )

    documents_count, chunks_count, dims = _validate_sqlite(
        db_path,
        expected_embed_dim=expected_embed_dim,
    )
    sample_query_hits = _run_sample_query(
        sample_query=sample_query,
        index_dir=index_dir,
        db_path=db_path,
        embedding_client=embedding_client,
    )

    return {
        "db_path": str(db_path),
        "documents": documents_count,
        "chunks": chunks_count,
        "min_embedding_dim": min(dims),
        "max_embedding_dim": max(dims),
        "distinct_embedding_dims": dims,
        "expected_embedding_dim": expected_embed_dim,
        "sample_query": sample_query,
        "sample_query_hits": sample_query_hits,
    }


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    settings = get_settings()

    try:
        payload = _resolve_payload(args.payload_json)
        db_path = Path(str(payload.get("db_path", settings.rag_db_path)))
        index_dir = Path(str(payload.get("index_dir", settings.rag_index_dir)))
        expected_embed_dim = _payload_int(
            payload,
            "expected_embed_dim",
            settings.rag_expected_embed_dim,
            minimum=0,
        )
        sample_query = str(payload.get("sample_query", settings.rag_verify_sample_query))

        embedding_client = OllamaEmbeddingClient(
            base_url=settings.ollama_embed_base_url,
            model=settings.ollama_embed_model,
            timeout_seconds=settings.ollama_timeout_seconds,
        )

        metrics = run_verify_index_job(
            db_path=db_path,
            index_dir=index_dir,
            expected_embed_dim=expected_embed_dim,
            sample_query=sample_query,
            embedding_client=embedding_client,
        )
    except Exception as exc:
        print(f"[rag-verify-index-runner] failed: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc

    print(json.dumps(metrics), flush=True)


if __name__ == "__main__":
    main()
