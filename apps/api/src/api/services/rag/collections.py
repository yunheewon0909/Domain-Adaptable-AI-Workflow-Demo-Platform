from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import math
from pathlib import Path
import re
from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.config import get_project_root, get_settings
from api.models import RAGCollectionRecord, RAGDocumentRecord
from api.services.rag.embedding_client import EmbeddingClientError
from api.services.runtime import EmbeddingRuntime, get_embedding_runtime

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - exercised only when dependency unavailable
    PdfReader = None


def _next_prefixed_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _collections_root() -> Path:
    return get_project_root() / "data" / "rag_collections"


def _sanitize_filename(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    return sanitized or "document"


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _extract_preview_text(content: bytes, mime_type: str) -> tuple[str, str]:
    normalized_mime_type = mime_type.lower()
    if normalized_mime_type in {"text/plain", "text/markdown", "text/x-markdown"}:
        return _normalize_text(content.decode("utf-8", errors="ignore")), "utf8"
    if normalized_mime_type == "application/pdf":
        if PdfReader is None:
            return _normalize_text(
                content.decode("latin-1", errors="ignore")
            ), "pdf-fallback"
        reader = PdfReader(BytesIO(content))
        extracted = "\n".join((page.extract_text() or "") for page in reader.pages)
        if not _normalize_text(extracted):
            metadata = reader.metadata or {}
            extracted = " ".join(
                str(value)
                for key, value in metadata.items()
                if key in {"/Title", "/Subject"} and str(value).strip()
            )
        return _normalize_text(extracted), "pypdf"
    return _normalize_text(content.decode("utf-8", errors="ignore")), "fallback"


def _tokenize(value: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", value.lower()) if token]


def _lexical_score(query: str, text: str) -> float:
    if not query or not text:
        return 0.0
    query_tokens = _tokenize(query)
    if not query_tokens:
        return 0.0
    text_tokens = _tokenize(text)
    if not text_tokens:
        return 0.0
    counts: dict[str, int] = {}
    for token in text_tokens:
        counts[token] = counts.get(token, 0) + 1
    return float(sum(counts.get(token, 0) for token in query_tokens))


_embedding_client: EmbeddingRuntime | None = None


def _get_embedding_client() -> EmbeddingRuntime | None:
    """Lazy-initialize the configured embedding runtime.

    Returns None when no embedding model is configured (e.g. test env), so
    callers can degrade to lexical scoring without forcing an HTTP call.
    """
    global _embedding_client
    settings = get_settings()
    model = (settings.llm_embed_model or "").strip()
    if not model:
        return None
    if _embedding_client is None:
        _embedding_client = get_embedding_runtime()
    return _embedding_client


def _embed_text(text: str) -> list[float] | None:
    """Embed a single text via the configured runtime, or None if unavailable."""
    client = _get_embedding_client()
    if client is None:
        return None
    try:
        vectors = client.embed_texts([text])
    except EmbeddingClientError:
        return None
    return vectors[0] if vectors else None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / math.sqrt(norm_a * norm_b)


def _serialize_document(document: RAGDocumentRecord) -> dict[str, Any]:
    metadata = document.metadata_json or {}
    return {
        "id": document.id,
        "collection_id": document.collection_id,
        "filename": document.filename,
        "mime_type": document.mime_type,
        "source_type": document.source_type,
        "status": document.status,
        "checksum": document.checksum,
        "metadata_json": metadata,
        "text_preview": metadata.get("text_preview", ""),
        "preview_excerpt": metadata.get("text_preview", "")[:500],
        "preview_length": metadata.get("text_length", 0),
        "parse_method": metadata.get("parse_method"),
        "created_at": document.created_at.isoformat()
        if document.created_at is not None
        else None,
        "updated_at": document.updated_at.isoformat()
        if document.updated_at is not None
        else None,
    }


def _serialize_collection(
    collection: RAGCollectionRecord, documents: list[RAGDocumentRecord]
) -> dict[str, Any]:
    return {
        "id": collection.id,
        "name": collection.name,
        "description": collection.description,
        "embedding_model": collection.embedding_model,
        "chunking_policy_json": collection.chunking_policy_json,
        "index_status": collection.index_status,
        "document_count": len(documents),
        "documents": [_serialize_document(document) for document in documents],
        "created_at": collection.created_at.isoformat()
        if collection.created_at is not None
        else None,
        "updated_at": collection.updated_at.isoformat()
        if collection.updated_at is not None
        else None,
    }


def create_collection(
    session: Session,
    *,
    name: str,
    description: str | None,
    embedding_model: str | None,
    chunking_policy_json: dict[str, Any] | None,
) -> dict[str, Any]:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    embedding = (embedding_model or settings.llm_embed_model).strip()
    policy = chunking_policy_json or {
        "chunk_size": settings.rag_chunk_size,
        "chunk_overlap": settings.rag_chunk_overlap,
    }
    collection = RAGCollectionRecord(
        id=_next_prefixed_id("rag-collection"),
        name=name.strip(),
        description=description.strip() if description else None,
        embedding_model=embedding,
        chunking_policy_json=policy,
        updated_at=now,
    )
    session.add(collection)
    session.commit()
    return get_collection(session, collection.id) or {"id": collection.id}


def list_collections(session: Session) -> list[dict[str, Any]]:
    collections = session.scalars(
        select(RAGCollectionRecord).order_by(
            RAGCollectionRecord.created_at.desc(), RAGCollectionRecord.id.desc()
        )
    ).all()
    documents = session.scalars(select(RAGDocumentRecord)).all()
    documents_by_collection: dict[str, list[RAGDocumentRecord]] = {}
    for document in documents:
        documents_by_collection.setdefault(document.collection_id, []).append(document)
    return [
        _serialize_collection(
            collection, documents_by_collection.get(collection.id, [])
        )
        for collection in collections
    ]


def get_collection(session: Session, collection_id: str) -> dict[str, Any] | None:
    collection = session.get(RAGCollectionRecord, collection_id)
    if collection is None:
        return None
    documents = session.scalars(
        select(RAGDocumentRecord)
        .where(RAGDocumentRecord.collection_id == collection_id)
        .order_by(RAGDocumentRecord.created_at.desc(), RAGDocumentRecord.id.desc())
    ).all()
    return _serialize_collection(collection, list(documents))


def add_collection_document(
    session: Session,
    *,
    collection_id: str,
    filename: str,
    mime_type: str,
    source_type: str,
    content: bytes,
) -> dict[str, Any]:
    collection = session.get(RAGCollectionRecord, collection_id)
    if collection is None:
        raise KeyError(collection_id)

    now = datetime.now(timezone.utc)
    checksum = hashlib.sha256(content).hexdigest()
    preview_text, parse_method = _extract_preview_text(content, mime_type)
    status = "parsed" if preview_text else "uploaded"
    storage_dir = _collections_root() / collection_id / "documents"
    storage_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix

    document_id = _next_prefixed_id("rag-doc")
    stored_filename = f"{document_id}{suffix}" if suffix else document_id
    storage_path = storage_dir / _sanitize_filename(stored_filename)
    embedding_vector = _embed_text(preview_text) if preview_text else None
    metadata_json: dict[str, Any] = {
        "storage_path": str(storage_path),
        "text_preview": preview_text[:4000],
        "text_length": len(preview_text),
        "parse_method": parse_method,
        "chunk_preview": [
            preview_text[i : i + 300]
            for i in range(0, min(len(preview_text), 900), 300)
        ]
        if preview_text
        else [],
    }
    if embedding_vector is not None:
        metadata_json["embedding"] = embedding_vector
    document = RAGDocumentRecord(
        id=document_id,
        collection_id=collection_id,
        filename=filename,
        mime_type=mime_type,
        source_type=source_type,
        status=status,
        checksum=checksum,
        metadata_json=metadata_json,
        updated_at=now,
    )
    session.add(document)
    collection.updated_at = now
    session.flush()
    storage_path.write_bytes(content)
    session.commit()
    return get_document(session, document.id) or {"id": document.id}


def list_collection_documents(
    session: Session, collection_id: str
) -> list[dict[str, Any]]:
    documents = session.scalars(
        select(RAGDocumentRecord)
        .where(RAGDocumentRecord.collection_id == collection_id)
        .order_by(RAGDocumentRecord.created_at.desc(), RAGDocumentRecord.id.desc())
    ).all()
    return [_serialize_document(document) for document in documents]


def get_document(session: Session, document_id: str) -> dict[str, Any] | None:
    document = session.get(RAGDocumentRecord, document_id)
    if document is None:
        return None
    return _serialize_document(document)


def delete_collection(session: Session, collection_id: str) -> dict[str, Any]:
    """Delete a RAG collection, all its documents, and the on-disk storage.

    Cascade is explicit here (no FK ON DELETE) because the documents table
    keeps `collection_id` as a plain string column and reviewers will hit a
    constraint error otherwise. The collection storage directory under
    `data/rag_collections/<id>/` is removed wholesale after the row commits.
    """
    import shutil as _shutil

    collection = session.get(RAGCollectionRecord, collection_id)
    if collection is None:
        raise KeyError(collection_id)

    documents = session.scalars(
        select(RAGDocumentRecord).where(
            RAGDocumentRecord.collection_id == collection_id
        )
    ).all()
    document_count = len(documents)
    for document in documents:
        session.delete(document)
    # Flush the child deletes before deleting the parent so Postgres sees
    # them in the right order (the FK has no ON DELETE CASCADE).
    session.flush()
    session.delete(collection)
    session.commit()

    storage_dir = _collections_root() / collection_id
    storage_deleted = False
    if storage_dir.exists():
        _shutil.rmtree(storage_dir, ignore_errors=True)
        storage_deleted = not storage_dir.exists()
    return {
        "collection_id": collection_id,
        "deleted": True,
        "document_count": document_count,
        "storage_deleted": storage_deleted,
    }


def delete_document(session: Session, document_id: str) -> dict[str, Any]:
    document = session.get(RAGDocumentRecord, document_id)
    if document is None:
        raise KeyError(document_id)

    metadata = dict(document.metadata_json or {})
    storage_path_raw = str(metadata.get("storage_path") or "").strip()
    collection = session.get(RAGCollectionRecord, document.collection_id)
    now = datetime.now(timezone.utc)
    if collection is not None:
        collection.updated_at = now
    storage_deleted = False
    response = {
        "document_id": document.id,
        "collection_id": document.collection_id,
        "deleted": True,
        "storage_deleted": storage_deleted,
    }
    session.delete(document)
    session.commit()
    if storage_path_raw:
        storage_path = Path(storage_path_raw)
        if storage_path.exists():
            storage_path.unlink()
            storage_deleted = True
            response["storage_deleted"] = True
    return response


def rename_collection(
    session: Session, collection_id: str, name: str
) -> dict[str, Any]:
    collection = session.get(RAGCollectionRecord, collection_id)
    if collection is None:
        raise KeyError(collection_id)
    collection.name = name.strip()
    collection.updated_at = datetime.now(timezone.utc)
    session.commit()
    return get_collection(session, collection_id) or {"id": collection_id}


def rename_document(
    session: Session, document_id: str, filename: str
) -> dict[str, Any]:
    document = session.get(RAGDocumentRecord, document_id)
    if document is None:
        raise KeyError(document_id)
    document.filename = filename.strip()
    document.updated_at = datetime.now(timezone.utc)
    session.commit()
    return get_document(session, document_id) or {"id": document_id}


def update_document_content(
    session: Session,
    document_id: str,
    content_text: str,
    filename: str | None = None,
) -> dict[str, Any]:
    document = session.get(RAGDocumentRecord, document_id)
    if document is None:
        raise KeyError(document_id)

    content = content_text.encode("utf-8")
    now = datetime.now(timezone.utc)
    mime_type = "text/plain"
    checksum = hashlib.sha256(content).hexdigest()

    metadata = dict(document.metadata_json or {})
    storage_path_raw = str(metadata.get("storage_path") or "").strip()
    if storage_path_raw and Path(storage_path_raw).parent.is_dir():
        storage_path = Path(storage_path_raw)
    else:
        storage_dir = _collections_root() / document.collection_id / "documents"
        storage_dir.mkdir(parents=True, exist_ok=True)
        doc_filename = filename or document.filename
        suffix = Path(doc_filename).suffix or ".txt"
        storage_path = storage_dir / _sanitize_filename(f"{document_id}{suffix}")

    preview_text, parse_method = _extract_preview_text(content, mime_type)
    embedding_vector = _embed_text(preview_text) if preview_text else None
    metadata.update({
        "storage_path": str(storage_path),
        "text_preview": preview_text[:4000],
        "text_length": len(preview_text),
        "parse_method": parse_method,
        "chunk_preview": [
            preview_text[i : i + 300]
            for i in range(0, min(len(preview_text), 900), 300)
        ] if preview_text else [],
    })
    if embedding_vector is not None:
        metadata["embedding"] = embedding_vector

    document.checksum = checksum
    document.mime_type = mime_type
    document.status = "parsed" if preview_text else "uploaded"
    document.metadata_json = dict(metadata)
    if filename:
        document.filename = filename.strip()
    document.updated_at = now

    collection = session.get(RAGCollectionRecord, document.collection_id)
    if collection is not None:
        collection.updated_at = now

    session.commit()
    storage_path.write_bytes(content)
    return get_document(session, document_id) or {"id": document_id}


def add_collection_document_text(
    session: Session,
    *,
    collection_id: str,
    filename: str,
    content_text: str,
) -> dict[str, Any]:
    return add_collection_document(
        session,
        collection_id=collection_id,
        filename=filename.strip() or "document.txt",
        mime_type="text/plain",
        source_type="text",
        content=content_text.encode("utf-8"),
    )


SEED_COLLECTION_OWNER_TAG = "demo_seed"


@dataclass(frozen=True)
class _SeedDocumentSpec:
    document_id: str
    source_path: str
    filename: str
    mime_type: str


@dataclass(frozen=True)
class _SeedCollectionSpec:
    collection_id: str
    name: str
    description: str
    documents: tuple[_SeedDocumentSpec, ...]


_DEMO_SEED_COLLECTIONS: tuple[_SeedCollectionSpec, ...] = (
    _SeedCollectionSpec(
        collection_id="rag-collection-demo-ops",
        name="Demo Operations Handbook",
        description=(
            "Pre-seeded industrial operations knowledge base. Use it to demo "
            "RAG-grounded chat and to derive an evaluation testset."
        ),
        documents=(
            _SeedDocumentSpec(
                document_id="rag-doc-seed-ops-getting-started",
                source_path="data/sample_docs/getting_started.txt",
                filename="getting_started.txt",
                mime_type="text/plain",
            ),
            _SeedDocumentSpec(
                document_id="rag-doc-seed-ops-maintenance",
                source_path="data/sample_docs/maintenance.md",
                filename="maintenance.md",
                mime_type="text/markdown",
            ),
        ),
    ),
    _SeedCollectionSpec(
        collection_id="rag-collection-demo-enterprise",
        name="Demo Enterprise Knowledge",
        description=(
            "Pre-seeded enterprise enablement and pilot notes. Second "
            "collection for grounded-chat or QA-dataset experimentation."
        ),
        documents=(
            _SeedDocumentSpec(
                document_id="rag-doc-seed-enterprise-enablement",
                source_path="data/datasets/enterprise_docs/source/quarterly_enablement.md",
                filename="quarterly_enablement.md",
                mime_type="text/markdown",
            ),
            _SeedDocumentSpec(
                document_id="rag-doc-seed-enterprise-pilot",
                source_path="data/datasets/enterprise_docs/source/pilot_notes.md",
                filename="pilot_notes.md",
                mime_type="text/markdown",
            ),
        ),
    ),
)


def _seed_document(
    session: Session,
    *,
    collection_id: str,
    spec: _SeedDocumentSpec,
    content: bytes,
) -> RAGDocumentRecord:
    now = datetime.now(timezone.utc)
    checksum = hashlib.sha256(content).hexdigest()
    storage_dir = _collections_root() / collection_id / "documents"
    storage_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(spec.filename).suffix
    stored_filename = f"{spec.document_id}{suffix}" if suffix else spec.document_id
    storage_path = storage_dir / _sanitize_filename(stored_filename)
    storage_path.write_bytes(content)

    preview_text, parse_method = _extract_preview_text(content, spec.mime_type)
    status = "parsed" if preview_text else "uploaded"
    metadata_json = {
        "storage_path": str(storage_path),
        "text_preview": preview_text[:4000],
        "text_length": len(preview_text),
        "parse_method": parse_method,
        "chunk_preview": [
            preview_text[i : i + 300]
            for i in range(0, min(len(preview_text), 900), 300)
        ]
        if preview_text
        else [],
        "owner_tag": SEED_COLLECTION_OWNER_TAG,
        "seed_source_path": spec.source_path,
    }
    record = RAGDocumentRecord(
        id=spec.document_id,
        collection_id=collection_id,
        filename=spec.filename,
        mime_type=spec.mime_type,
        source_type="seed",
        status=status,
        checksum=checksum,
        metadata_json=metadata_json,
        updated_at=now,
    )
    session.add(record)
    return record


def ensure_default_rag_collections(session: Session) -> list[dict[str, Any]]:
    """Seed deterministic demo RAG collections if they are missing.

    Idempotent: existing collection/document records keyed by the seed ids are
    left untouched, so reviewers can edit or delete the seed without it being
    silently restored on the next API restart. Documents are only re-created
    when both the seed source file is present on disk and the record does not
    already exist.
    """
    settings = get_settings()
    project_root = get_project_root()
    now = datetime.now(timezone.utc)
    seeded: list[dict[str, Any]] = []
    changed = False

    for spec in _DEMO_SEED_COLLECTIONS:
        collection = session.get(RAGCollectionRecord, spec.collection_id)
        is_new_collection = collection is None
        if is_new_collection:
            collection = RAGCollectionRecord(
                id=spec.collection_id,
                name=spec.name,
                description=spec.description,
                embedding_model=settings.llm_embed_model,
                chunking_policy_json={
                    "chunk_size": settings.rag_chunk_size,
                    "chunk_overlap": settings.rag_chunk_overlap,
                    "owner_tag": SEED_COLLECTION_OWNER_TAG,
                },
                updated_at=now,
            )
            session.add(collection)
            session.flush()
            changed = True
        else:
            # Re-sync description + embedding_model on seed-owned rows when the
            # spec drifts (e.g. legacy `nomic-embed-text` rows after the LM
            # Studio cut-over). Rows whose owner_tag no longer matches are
            # treated as reviewer-modified and left alone.
            assert collection is not None  # narrowed: not new => exists
            policy = collection.chunking_policy_json or {}
            if policy.get("owner_tag") == SEED_COLLECTION_OWNER_TAG:
                desired_embed = settings.llm_embed_model
                if (
                    collection.description != spec.description
                    or collection.embedding_model != desired_embed
                ):
                    collection.description = spec.description
                    collection.embedding_model = desired_embed
                    changed = True

        # Only populate documents on first creation. A reviewer deleting a seed
        # document should not see it silently restored on the next restart;
        # deleting the whole collection is the documented way to re-seed.
        if is_new_collection:
            assert collection is not None  # narrowed: created on the branch above
            for doc_spec in spec.documents:
                source_path = project_root / doc_spec.source_path
                if not source_path.is_file():
                    continue
                content = source_path.read_bytes()
                _seed_document(
                    session,
                    collection_id=spec.collection_id,
                    spec=doc_spec,
                    content=content,
                )
                changed = True

        seeded.append({"id": spec.collection_id, "name": spec.name})

    if changed:
        session.commit()
    return seeded


def preview_collection_retrieval(
    session: Session, *, collection_id: str, query: str, top_k: int = 3
) -> dict[str, Any]:
    collection = session.get(RAGCollectionRecord, collection_id)
    if collection is None:
        raise KeyError(collection_id)
    documents = session.scalars(
        select(RAGDocumentRecord).where(
            RAGDocumentRecord.collection_id == collection_id
        )
    ).all()
    query_embedding = _embed_text(query)
    scored_results: list[dict[str, Any]] = []
    for document in documents:
        metadata = document.metadata_json or {}
        preview_text = str(metadata.get("text_preview") or "")
        doc_embedding_raw = metadata.get("embedding")
        score = 0.0
        if (
            query_embedding is not None
            and isinstance(doc_embedding_raw, list)
            and doc_embedding_raw
        ):
            doc_embedding = [float(v) for v in doc_embedding_raw]
            score = _cosine_similarity(query_embedding, doc_embedding)
        else:
            # No embedding for either side (e.g. LM Studio unreachable, or the
            # doc was seeded before embeddings were wired in). Fall back to
            # lexical token overlap so retrieval still works in offline /
            # test environments.
            score = _lexical_score(query, preview_text)
        if score <= 0.0:
            continue
        scored_results.append(
            {
                "document_id": document.id,
                "filename": document.filename,
                "score": score,
                "excerpt": preview_text[:400],
                "status": document.status,
            }
        )
    scored_results.sort(key=lambda item: (-float(item["score"]), str(item["filename"])))
    return {
        "collection_id": collection.id,
        "collection_name": collection.name,
        "document_count": len(documents),
        "query": query,
        "top_k": top_k,
        "results": scored_results[: max(1, min(int(top_k), 10))],
    }
