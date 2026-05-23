from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
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
    collection = RAGCollectionRecord(
        id=_next_prefixed_id(session, RAGCollectionRecord, "rag-collection"),
        name=name.strip(),
        description=description.strip() if description else None,
        embedding_model=(embedding_model or settings.lmstudio_embed_model).strip(),
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
            "RAG-grounded chat and to derive a QA dataset for fine-tuning."
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
                embedding_model=settings.lmstudio_embed_model,
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
                desired_embed = settings.lmstudio_embed_model
                if (
                    collection.description != spec.description
                    or collection.embedding_model != desired_embed
                ):
                    collection.description = spec.description
                    collection.embedding_model = desired_embed
                    collection.updated_at = now
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
                collection.updated_at = now
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
        "document_count": len(documents),
        "query": query,
        "top_k": top_k,
        "results": scored_results[: max(1, min(int(top_k), 10))],
    }
