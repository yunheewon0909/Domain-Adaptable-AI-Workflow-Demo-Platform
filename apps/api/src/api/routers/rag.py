from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from api.db import get_engine
from api.services.rag.collections import (
    add_collection_document,
    create_collection,
    delete_collection,
    delete_document,
    get_collection,
    get_document,
    list_collection_documents,
    list_collections,
    preview_collection_retrieval,
)

router = APIRouter(tags=["rag"])


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
