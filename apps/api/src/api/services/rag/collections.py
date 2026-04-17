from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
from io import BytesIO
from pathlib import Path
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.config import get_project_root, get_settings
from api.models import RAGCollectionRecord, RAGDocumentRecord

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - exercised only when dependency unavailable
    PdfReader = None


def _next_prefixed_id(session: Session, model: type, prefix: str) -> str:
    next_value = 1
    for existing_id in session.scalars(select(model.id)).all():
        suffix = str(existing_id).replace(f"{prefix}-", "", 1)
        if suffix.isdigit():
            next_value = max(next_value, int(suffix) + 1)
    return f"{prefix}-{next_value}"


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
    collection = RAGCollectionRecord(
        id=_next_prefixed_id(session, RAGCollectionRecord, "rag-collection"),
        name=name.strip(),
        description=description.strip() if description else None,
        embedding_model=(embedding_model or settings.ollama_embed_model).strip(),
        chunking_policy_json=chunking_policy_json
        or {
            "chunk_size": settings.rag_chunk_size,
            "chunk_overlap": settings.rag_chunk_overlap,
        },
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
    document_id = _next_prefixed_id(session, RAGDocumentRecord, "rag-doc")
    checksum = hashlib.sha256(content).hexdigest()
    storage_dir = _collections_root() / collection_id / "documents"
    storage_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix
    stored_filename = f"{document_id}{suffix}" if suffix else document_id
    storage_path = storage_dir / _sanitize_filename(stored_filename)
    storage_path.write_bytes(content)

    preview_text, parse_method = _extract_preview_text(content, mime_type)
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
    }
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
    query_tokens = _tokenize(query)
    scored_results: list[dict[str, Any]] = []
    for document in documents:
        preview_text = str((document.metadata_json or {}).get("text_preview") or "")
        text_tokens = Counter(_tokenize(preview_text))
        score = sum(text_tokens[token] for token in query_tokens)
        if score <= 0:
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
    scored_results.sort(key=lambda item: (-int(item["score"]), str(item["filename"])))
    return {
        "collection_id": collection.id,
        "collection_name": collection.name,
        "query": query,
        "top_k": top_k,
        "results": scored_results[: max(1, min(int(top_k), 10))],
    }
