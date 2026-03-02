from datetime import datetime, timezone
import json
import re
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.config import get_settings
from api.db import get_engine
from api.llm import LLMClient, LLMClientError, OllamaChatClient
from api.models import JobRecord
from api.services.rag.embedding_client import EmbeddingClient, OllamaEmbeddingClient
from api.services.rag import search_index

app = FastAPI(title="Industrial AI Harness API", version="0.1.0")


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    k: int = Field(default=3, ge=1, le=20)


class ReindexEnqueueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload_json: dict[str, Any] | None = None


def _enqueue_job(
    *,
    job_type: str,
    payload_json: dict[str, Any] | None = None,
    active_types: tuple[str, ...] | None = None,
) -> JSONResponse:
    conflict_types = active_types or (job_type,)

    with Session(get_engine()) as session:
        existing = session.scalar(
            select(JobRecord)
            .where(JobRecord.type.in_(conflict_types))
            .where(JobRecord.status.in_(["queued", "running"]))
            .order_by(JobRecord.created_at.asc(), JobRecord.id.asc())
            .limit(1)
        )
        if existing is not None:
            return JSONResponse(
                status_code=409,
                content={
                    "detail": f"{job_type} already queued/running",
                    "existing_job_id": existing.id,
                },
            )

        job = JobRecord(
            id=_next_job_id(session),
            type=job_type,
            status="queued",
            payload_json=payload_json,
            attempts=0,
            max_attempts=3,
            updated_at=datetime.now(timezone.utc),
        )
        session.add(job)
        session.commit()
        job_id = job.id
        job_status = job.status

    return JSONResponse(status_code=202, content={"job_id": job_id, "status": job_status})


@app.on_event("startup")
def startup() -> None:
    get_engine()


def get_llm_client() -> LLMClient:
    settings = get_settings()
    return OllamaChatClient(
        base_url=settings.ollama_base_url,
        default_model=settings.ollama_model,
        fallback_model=settings.ollama_fallback_model,
        timeout_seconds=settings.ollama_timeout_seconds,
    )


def get_embedding_client() -> EmbeddingClient:
    settings = get_settings()
    return OllamaEmbeddingClient(
        base_url=settings.ollama_embed_base_url,
        model=settings.ollama_embed_model,
        timeout_seconds=settings.ollama_timeout_seconds,
    )


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _job_summary(job: JobRecord) -> dict[str, Any]:
    return {
        "id": job.id,
        "type": job.type,
        "status": job.status,
    }


def _job_detail(job: JobRecord) -> dict[str, Any]:
    payload_json = job.payload_json
    if isinstance(payload_json, str):
        try:
            parsed_payload = json.loads(payload_json)
        except json.JSONDecodeError:
            parsed_payload = None
        else:
            payload_json = parsed_payload if isinstance(parsed_payload, dict) else None

    result_json = job.result_json
    if isinstance(result_json, str):
        try:
            parsed_result = json.loads(result_json)
        except json.JSONDecodeError:
            parsed_result = None
        else:
            result_json = parsed_result if isinstance(parsed_result, dict) else None

    return {
        "id": job.id,
        "type": job.type,
        "status": job.status,
        "payload_json": payload_json,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "created_at": _to_iso(job.created_at),
        "updated_at": _to_iso(job.updated_at),
        "started_at": _to_iso(job.started_at),
        "finished_at": _to_iso(job.finished_at),
        "error": job.error,
        "result_json": result_json,
    }


def _extract_numeric_suffix(value: str) -> int | None:
    match = re.search(r"(\d+)$", value)
    if match is None:
        return None
    return int(match.group(1))


def _next_job_id(session: Session) -> str:
    next_id = 1
    for existing_id in session.scalars(select(JobRecord.id)).all():
        parsed = _extract_numeric_suffix(str(existing_id))
        if parsed is None:
            continue
        next_id = max(next_id, parsed + 1)
    return str(next_id)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/rag/reindex")
def enqueue_rag_reindex(request: ReindexEnqueueRequest | None = None) -> JSONResponse:
    payload_json = request.payload_json if request is not None else None
    return _enqueue_job(job_type="rag_reindex", payload_json=payload_json)


@app.post("/rag/warmup")
def enqueue_rag_warmup() -> JSONResponse:
    return _enqueue_job(job_type="ollama_warmup")


@app.post("/rag/verify")
def enqueue_rag_verify_index() -> JSONResponse:
    return _enqueue_job(job_type="rag_verify_index")


@app.get("/jobs")
def list_jobs(
    type: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    with Session(get_engine()) as session:
        stmt = select(JobRecord)
        if type is not None:
            stmt = stmt.where(JobRecord.type == type)
        if status is not None:
            stmt = stmt.where(JobRecord.status == status)

        jobs = session.scalars(
            stmt.order_by(JobRecord.created_at.asc(), JobRecord.id.asc())
        ).all()

    return [_job_summary(job) for job in jobs]


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    with Session(get_engine()) as session:
        job = session.get(JobRecord, job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _job_detail(job)


@app.get("/rag/search")
def rag_search(
    q: str,
    embedding_client: Annotated[EmbeddingClient, Depends(get_embedding_client)],
    k: int = 3,
) -> list[dict[str, object]]:
    if not q.strip():
        raise HTTPException(status_code=400, detail="q must not be empty")

    settings = get_settings()
    top_k = max(1, min(k, 20))

    try:
        hits = search_index(
            index_dir=Path(settings.rag_index_dir),
            db_path=Path(settings.rag_db_path),
            query_text=q,
            top_k=top_k,
            embedding_client=embedding_client,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return [
        {
            "chunk_id": hit.chunk_id,
            "source_path": hit.source_path,
            "score": round(hit.score, 6),
            "text": hit.text,
        }
        for hit in hits
    ]


@app.post("/ask")
def ask(
    request: AskRequest,
    llm_client: Annotated[LLMClient, Depends(get_llm_client)],
    embedding_client: Annotated[EmbeddingClient, Depends(get_embedding_client)],
) -> dict[str, Any]:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question must not be empty")

    settings = get_settings()

    try:
        hits = search_index(
            index_dir=Path(settings.rag_index_dir),
            db_path=Path(settings.rag_db_path),
            query_text=question,
            top_k=request.k,
            embedding_client=embedding_client,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    context = "\n\n".join(
        f"[{hit.source_path}#{hit.chunk_id}]\n{hit.text}"
        for hit in hits
    ) or "No relevant context found in local retrieval index."

    try:
        chat_result = llm_client.generate_answer(question=question, context=context)
    except LLMClientError as exc:
        raise HTTPException(status_code=502, detail=f"LLM request failed: {exc}") from exc

    return {
        "answer": chat_result.answer,
        "sources": [
            {
                "chunk_id": hit.chunk_id,
                "source_path": hit.source_path,
                "score": round(hit.score, 6),
                "text": hit.text,
            }
            for hit in hits
        ],
        "meta": {
            "provider": "ollama",
            "model": chat_result.model,
            "used_fallback": chat_result.used_fallback,
            "retrieval_k": request.k,
            "retrieved_count": len(hits),
            "ollama_base_url": settings.ollama_base_url,
        },
    }


def run() -> None:
    import uvicorn

    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    run()
