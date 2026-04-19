from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from api.config import get_settings
from api.db import get_engine
from api.dependencies import get_embedding_client, get_llm_client
from api.llm import LLMClient, LLMClientError
from api.services.datasets import DatasetNotFoundError, resolve_dataset
from api.services.jobs import create_job, find_conflicting_job
from api.services.retrieval.service import retrieve_evidence
from api.services.rag.collections import (
    add_collection_document,
    create_collection,
    delete_document,
    get_collection,
    get_document,
    list_collection_documents,
    list_collections,
    preview_collection_retrieval,
)
from api.services.rag.embedding_client import EmbeddingClient

router = APIRouter(tags=["rag"])


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    k: int = Field(default=3, ge=1, le=20)
    dataset_key: str | None = None


class ReindexEnqueueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload_json: dict[str, Any] | None = None


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


def _job_type_for_reindex_mode(mode: Literal["full", "incremental"]) -> str:
    if mode == "incremental":
        return "rag_reindex_incremental"
    return "rag_reindex"


def _enqueue_operational_job(
    *,
    job_type: str,
    payload_json: dict[str, Any] | None = None,
    active_types: tuple[str, ...] | None = None,
) -> JSONResponse:
    with Session(get_engine()) as session:
        existing = find_conflicting_job(
            session,
            job_type=job_type,
            active_types=active_types,
        )
        if existing is not None:
            return JSONResponse(
                status_code=409,
                content={
                    "detail": f"{job_type} already queued/running",
                    "existing_job_id": existing.id,
                },
            )

        job = create_job(
            session,
            job_type=job_type,
            payload_json=payload_json,
        )
    return JSONResponse(
        status_code=202, content={"job_id": job.id, "status": job.status}
    )


@router.post("/rag/reindex")
def enqueue_rag_reindex(
    request: ReindexEnqueueRequest | None = None,
    mode: Literal["full", "incremental"] = Query(default="full"),
) -> JSONResponse:
    payload_json = request.payload_json if request is not None else None
    return _enqueue_operational_job(
        job_type=_job_type_for_reindex_mode(mode),
        payload_json=payload_json,
    )


@router.post("/rag/warmup")
def enqueue_rag_warmup() -> JSONResponse:
    return _enqueue_operational_job(job_type="ollama_warmup")


@router.post("/rag/verify")
def enqueue_rag_verify_index() -> JSONResponse:
    return _enqueue_operational_job(job_type="rag_verify_index")


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


@router.get("/rag/search")
def rag_search(
    q: str,
    embedding_client: Annotated[EmbeddingClient, Depends(get_embedding_client)],
    k: int = 3,
    dataset_key: str | None = Query(default=None),
) -> list[dict[str, object]]:
    if not q.strip():
        raise HTTPException(status_code=400, detail="q must not be empty")

    with Session(get_engine()) as session:
        try:
            dataset = resolve_dataset(session, dataset_key)
        except DatasetNotFoundError as exc:
            raise HTTPException(status_code=404, detail="dataset not found") from exc

    try:
        evidence = retrieve_evidence(
            dataset=dataset,
            query_text=q,
            top_k=max(1, min(k, 20)),
            embedding_client=embedding_client,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return [item.model_dump(mode="json") for item in evidence]


@router.post("/ask")
def ask(
    request: AskRequest,
    llm_client: Annotated[LLMClient, Depends(get_llm_client)],
    embedding_client: Annotated[EmbeddingClient, Depends(get_embedding_client)],
) -> dict[str, Any]:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question must not be empty")

    with Session(get_engine()) as session:
        try:
            dataset = resolve_dataset(session, request.dataset_key)
        except DatasetNotFoundError as exc:
            raise HTTPException(status_code=404, detail="dataset not found") from exc

    try:
        evidence = retrieve_evidence(
            dataset=dataset,
            query_text=question,
            top_k=request.k,
            embedding_client=embedding_client,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    context = (
        "\n\n".join(
            f"[{item.source_path}#{item.chunk_id}]\n{item.text}" for item in evidence
        )
        or "No relevant context found in local retrieval index."
    )

    try:
        chat_result = llm_client.generate_answer(question=question, context=context)
    except LLMClientError as exc:
        raise HTTPException(
            status_code=502, detail=f"LLM request failed: {exc}"
        ) from exc

    settings = get_settings()

    return {
        "answer": chat_result.answer,
        "sources": [item.model_dump(mode="json") for item in evidence],
        "meta": {
            "provider": "ollama",
            "model": chat_result.model,
            "used_fallback": chat_result.used_fallback,
            "retrieval_k": request.k,
            "retrieved_count": len(evidence),
            "ollama_base_url": settings.ollama_base_url,
            "dataset_key": dataset.key,
            "dataset_title": dataset.title,
        },
    }
