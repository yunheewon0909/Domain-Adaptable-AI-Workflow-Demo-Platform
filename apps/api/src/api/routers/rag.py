from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
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
    return JSONResponse(status_code=202, content={"job_id": job.id, "status": job.status})


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

    context = "\n\n".join(
        f"[{item.source_path}#{item.chunk_id}]\n{item.text}"
        for item in evidence
    ) or "No relevant context found in local retrieval index."

    try:
        chat_result = llm_client.generate_answer(question=question, context=context)
    except LLMClientError as exc:
        raise HTTPException(status_code=502, detail=f"LLM request failed: {exc}") from exc

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
