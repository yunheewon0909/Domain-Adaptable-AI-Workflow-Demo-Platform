"""Model listing + ad-hoc inference, backed by the configured runtime.

After fine-tuning was removed (ADR 0008) there is no model registry: the set of
available models is simply what the runtime (Ollama by default) serves. This
router exposes that list and a small ``/inference/run`` helper with optional RAG
grounding, used by the Open WebUI tool and the admin dashboard.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict, Field

from api.db import get_engine
from api.dependencies import get_llm_client
from api.llm import LLMClient, LLMClientError
from api.services.rag.collections import preview_collection_retrieval
from api.services.runtime import get_chat_runtime

router = APIRouter(tags=["models"])

OWNED_BY = "domain-adaptable-ai-platform"


class InferenceRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1)
    model: str | None = None
    rag_collection_id: str | None = None
    top_k: int = Field(default=4, ge=1, le=10)
    temperature: float = Field(default=0, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)


def _runtime_model_ids() -> list[str]:
    try:
        return get_chat_runtime().list_model_ids()
    except Exception:
        # Runtime unreachable (e.g. Ollama not up yet) — surface an empty list
        # rather than a 500 so the dashboard/tool degrade gracefully.
        return []


@router.get("/models")
def list_models_endpoint() -> dict[str, Any]:
    ids = _runtime_model_ids()
    return {
        "object": "list",
        "data": [
            {"id": model_id, "object": "model", "owned_by": OWNED_BY}
            for model_id in ids
        ],
    }


@router.get("/models/{model_id}")
def get_model_endpoint(model_id: str) -> dict[str, Any]:
    if model_id not in _runtime_model_ids():
        raise HTTPException(status_code=404, detail="model not served by the runtime")
    return {"id": model_id, "object": "model", "owned_by": OWNED_BY}


@router.post("/inference/run")
def run_inference(
    request: InferenceRunRequest,
    llm_client: LLMClient = Depends(get_llm_client),
) -> dict[str, Any]:
    context = "No prior context provided."
    retrieval_preview: dict[str, Any] | None = None

    if request.rag_collection_id:
        with Session(get_engine()) as session:
            try:
                retrieval_preview = preview_collection_retrieval(
                    session,
                    collection_id=request.rag_collection_id,
                    query=request.prompt,
                    top_k=request.top_k,
                )
            except KeyError as exc:
                raise HTTPException(
                    status_code=404, detail="RAG collection not found"
                ) from exc
        context = (
            "\n\n".join(
                f"[{item['filename']}]\n{item['excerpt']}"
                for item in retrieval_preview.get("results", [])
            )
            or "No matching RAG collection context found."
        )

    try:
        result = llm_client.generate_answer(
            question=request.prompt,
            context=context,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
    except LLMClientError as exc:
        raise HTTPException(status_code=502, detail=f"LLM request failed: {exc}") from exc

    return {
        "answer": result.answer,
        "model": result.model,
        "rag_collection_id": request.rag_collection_id,
        "retrieval_preview": retrieval_preview,
    }
