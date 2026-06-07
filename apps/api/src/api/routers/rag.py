from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from sqlalchemy import select

from api.db import get_engine
from api.models import (
    RAGCollectionRecord,
    RAGEntityRecord,
    RAGRelationshipRecord,
)
from api.services.jobs import create_job, serialize_job_summary
from api.services.rag.collections import (
    add_collection_document,
    add_collection_document_text,
    create_collection,
    delete_collection,
    delete_document,
    get_collection,
    get_document,
    list_collection_documents,
    list_collections,
    preview_collection_retrieval,
    rename_collection,
    rename_document,
    update_document_content,
)
from api.services.rag.graph_retrieval import MODES, query_collection

router = APIRouter(tags=["rag"])


class GraphQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    mode: str = Field(default="local")
    top_k: int = Field(default=5, ge=1, le=20)


class CreateRAGCollectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str | None = None
    embedding_model: str | None = None
    chunking_policy_json: dict[str, Any] = Field(default_factory=dict)


class RetrievalPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    top_k: int = Field(default=3, ge=1, le=10)


class RenameRAGCollectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)


class RenameRAGDocumentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1)


class UpdateRAGDocumentContentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str
    filename: str | None = None


class CreateTextDocumentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(default="document.txt", min_length=1)
    content: str


@router.post("/rag-collections", status_code=201)
def post_rag_collection(request: CreateRAGCollectionRequest) -> dict[str, Any]:
    with Session(get_engine()) as session:
        return create_collection(
            session,
            name=request.name,
            description=request.description,
            embedding_model=request.embedding_model,
            chunking_policy_json=request.chunking_policy_json,
        )


@router.post("/rag-collections/{collection_id}/reveal")
def post_rag_reveal(collection_id: str) -> dict[str, Any]:
    """Open the collection's on-disk storage dir in Finder (macOS only).

    Demo convenience: lets the reviewer inspect the raw uploaded files
    + the per-document storage layout without `cd`-ing in a terminal.
    """
    import subprocess
    from pathlib import Path

    from api.services.rag.collections import _collections_root

    with Session(get_engine()) as session:
        collection = get_collection(session, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="RAG collection not found")
    storage = Path(_collections_root()) / collection_id
    storage.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["open", str(storage)], check=True, timeout=5)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"`open` failed ({exc}); macOS Finder is required for this convenience endpoint.",
        ) from exc
    return {"collection_id": collection_id, "opened": str(storage)}


@router.get("/rag-collections")
def get_rag_collections() -> list[dict[str, Any]]:
    with Session(get_engine()) as session:
        return list_collections(session)


@router.get("/rag-collections/{collection_id}")
def get_rag_collection(collection_id: str) -> dict[str, Any]:
    with Session(get_engine()) as session:
        collection = get_collection(session, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="RAG collection not found")
    return collection


@router.delete("/rag-collections/{collection_id}")
def delete_rag_collection(collection_id: str) -> dict[str, Any]:
    with Session(get_engine()) as session:
        try:
            return delete_collection(session, collection_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="RAG collection not found"
            ) from exc


@router.patch("/rag-collections/{collection_id}")
def patch_rag_collection(
    collection_id: str, request: RenameRAGCollectionRequest
) -> dict[str, Any]:
    with Session(get_engine()) as session:
        try:
            return rename_collection(session, collection_id, request.name)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="RAG collection not found"
            ) from exc


@router.post("/rag-collections/{collection_id}/documents/text", status_code=201)
def post_rag_collection_document_text(
    collection_id: str, request: CreateTextDocumentRequest
) -> dict[str, Any]:
    with Session(get_engine()) as session:
        try:
            return add_collection_document_text(
                session,
                collection_id=collection_id,
                filename=request.filename,
                content_text=request.content,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="RAG collection not found"
            ) from exc


@router.post("/rag-collections/{collection_id}/documents", status_code=201)
async def post_rag_collection_document(
    collection_id: str,
    file: UploadFile = File(...),
    source_type: str = Query(default="upload"),
) -> dict[str, Any]:
    content = await file.read()
    with Session(get_engine()) as session:
        try:
            return add_collection_document(
                session,
                collection_id=collection_id,
                filename=file.filename or "uploaded-document",
                mime_type=file.content_type or "application/octet-stream",
                source_type=source_type,
                content=content,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="RAG collection not found"
            ) from exc


@router.get("/rag-collections/{collection_id}/documents")
def get_rag_collection_documents(collection_id: str) -> list[dict[str, Any]]:
    with Session(get_engine()) as session:
        collection = get_collection(session, collection_id)
        if collection is None:
            raise HTTPException(status_code=404, detail="RAG collection not found")
        return list_collection_documents(session, collection_id)


@router.get("/rag-documents/{document_id}")
def get_rag_document(document_id: str) -> dict[str, Any]:
    with Session(get_engine()) as session:
        document = get_document(session, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="RAG document not found")
    return document


@router.get("/rag-documents/{document_id}/content")
def get_rag_document_content(document_id: str) -> dict[str, Any]:
    """Return the full document text + metadata for the demo viewer.

    `/rag-documents/{id}` returns only the 4KB `text_preview` cap.
    This endpoint reads the original stored file from disk and returns
    the full text (up to a 256KB safety cap so a 1MB document doesn't
    bloat the response). Binary files come back base64-encoded as a
    fallback.
    """
    from pathlib import Path

    with Session(get_engine()) as session:
        document = get_document(session, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="RAG document not found")
    storage_path_raw = str(
        (document.get("metadata_json") or {}).get("storage_path") or ""
    ).strip()
    if not storage_path_raw:
        raise HTTPException(
            status_code=404,
            detail="document has no stored content on disk",
        )
    path = Path(storage_path_raw)
    if not path.is_file():
        raise HTTPException(
            status_code=410,
            detail="stored document file is missing on disk",
        )
    raw = path.read_bytes()
    truncated = len(raw) > 262_144
    if truncated:
        raw = raw[:262_144]
    try:
        text = raw.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        import base64

        text = base64.b64encode(raw).decode("ascii")
        encoding = "base64"
    return {
        "document_id": document.get("id"),
        "filename": document.get("filename"),
        "mime_type": document.get("mime_type"),
        "byte_length": path.stat().st_size,
        "encoding": encoding,
        "truncated": truncated,
        "content": text,
    }


@router.delete("/rag-documents/{document_id}")
def delete_rag_document(document_id: str) -> dict[str, Any]:
    with Session(get_engine()) as session:
        try:
            return delete_document(session, document_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="RAG document not found"
            ) from exc
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to delete stored document content: {exc}",
            ) from exc


@router.patch("/rag-documents/{document_id}")
def patch_rag_document(
    document_id: str, request: RenameRAGDocumentRequest
) -> dict[str, Any]:
    with Session(get_engine()) as session:
        try:
            return rename_document(session, document_id, request.filename)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="RAG document not found"
            ) from exc


@router.put("/rag-documents/{document_id}/content")
def put_rag_document_content(
    document_id: str, request: UpdateRAGDocumentContentRequest
) -> dict[str, Any]:
    with Session(get_engine()) as session:
        try:
            return update_document_content(
                session, document_id, request.content, request.filename
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="RAG document not found"
            ) from exc


@router.post("/rag-retrieval/preview")
def post_rag_retrieval_preview(request: RetrievalPreviewRequest) -> dict[str, Any]:
    with Session(get_engine()) as session:
        try:
            return preview_collection_retrieval(
                session,
                collection_id=request.collection_id,
                query=request.query,
                top_k=request.top_k,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="RAG collection not found"
            ) from exc


# --- Graph RAG (ADR 0010) -------------------------------------------------


@router.post("/rag-collections/{collection_id}/index", status_code=202)
def enqueue_collection_index(collection_id: str) -> dict[str, Any]:
    """Enqueue a Graph RAG (re)index job. The worker container processes it."""
    with Session(get_engine()) as session:
        if session.get(RAGCollectionRecord, collection_id) is None:
            raise HTTPException(status_code=404, detail="RAG collection not found")
        job = create_job(
            session,
            job_type="rag_index_collection",
            payload_json={"collection_id": collection_id},
        )
        return {"job": serialize_job_summary(job)}


@router.post("/rag-collections/{collection_id}/query")
def post_collection_query(
    collection_id: str, request: GraphQueryRequest
) -> dict[str, Any]:
    if request.mode not in MODES:
        raise HTTPException(
            status_code=400,
            detail=f"mode must be one of {sorted(MODES)}",
        )
    with Session(get_engine()) as session:
        try:
            return query_collection(
                session,
                collection_id=collection_id,
                query=request.query,
                mode=request.mode,
                top_k=request.top_k,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="RAG collection not found"
            ) from exc


@router.get("/rag-entities/{entity_id}")
def get_rag_entity(entity_id: str) -> dict[str, Any]:
    with Session(get_engine()) as session:
        entity = session.get(RAGEntityRecord, entity_id)
        if entity is None:
            raise HTTPException(status_code=404, detail="entity not found")
        rels = list(
            session.scalars(
                select(RAGRelationshipRecord).where(
                    (RAGRelationshipRecord.source_entity_id == entity_id)
                    | (RAGRelationshipRecord.target_entity_id == entity_id)
                )
            ).all()
        )
        return {
            "id": entity.id,
            "name": entity.name,
            "type": entity.type,
            "description": entity.description,
            "degree": entity.degree,
            "community_id": entity.community_id,
            "relationships": [
                {
                    "id": r.id,
                    "source_entity_id": r.source_entity_id,
                    "target_entity_id": r.target_entity_id,
                    "description": r.description,
                    "weight": r.weight,
                }
                for r in rels
            ],
        }


@router.get("/rag-collections/{collection_id}/subgraph")
def get_collection_subgraph(
    collection_id: str, limit: int = Query(default=100, ge=1, le=1000)
) -> dict[str, Any]:
    with Session(get_engine()) as session:
        if session.get(RAGCollectionRecord, collection_id) is None:
            raise HTTPException(status_code=404, detail="RAG collection not found")
        entities = list(
            session.scalars(
                select(RAGEntityRecord)
                .where(RAGEntityRecord.collection_id == collection_id)
                .order_by(RAGEntityRecord.degree.desc())
                .limit(limit)
            ).all()
        )
        entity_ids = {e.id for e in entities}
        rels = [
            r
            for r in session.scalars(
                select(RAGRelationshipRecord).where(
                    RAGRelationshipRecord.collection_id == collection_id
                )
            ).all()
            if r.source_entity_id in entity_ids and r.target_entity_id in entity_ids
        ]
        return {
            "collection_id": collection_id,
            "nodes": [
                {
                    "id": e.id,
                    "name": e.name,
                    "type": e.type,
                    "degree": e.degree,
                    "community_id": e.community_id,
                }
                for e in entities
            ],
            "edges": [
                {
                    "id": r.id,
                    "source": r.source_entity_id,
                    "target": r.target_entity_id,
                    "weight": r.weight,
                }
                for r in rels
            ],
        }
