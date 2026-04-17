from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from api.db import get_engine
from api.dependencies import get_llm_client
from api.llm import LLMClient, LLMClientError
from api.services.model_registry import (
    create_training_job,
    get_model,
    get_training_job,
    list_models,
    list_training_jobs,
    resolve_model_selection,
)
from api.services.rag.collections import preview_collection_retrieval

router = APIRouter(tags=["models"])


class CreateTrainingJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_version_id: str = Field(min_length=1)
    base_model_name: str = Field(min_length=1)
    training_method: str = Field(default="stub_adapter", min_length=1)
    hyperparams_json: dict[str, Any] = Field(default_factory=dict)


class InferenceRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1)
    model_id: str | None = None
    ollama_model_name: str | None = None
    rag_collection_id: str | None = None
    temperature: float = Field(default=0, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)
    top_k: int = Field(default=3, ge=1, le=10)


@router.post("/ft-training-jobs", status_code=202)
def post_ft_training_job(request: CreateTrainingJobRequest) -> dict[str, Any]:
    with Session(get_engine()) as session:
        try:
            return create_training_job(
                session,
                dataset_version_id=request.dataset_version_id,
                base_model_name=request.base_model_name,
                training_method=request.training_method,
                hyperparams_json=request.hyperparams_json,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="fine-tuning dataset version not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/ft-training-jobs")
def get_ft_training_jobs() -> list[dict[str, Any]]:
    with Session(get_engine()) as session:
        return list_training_jobs(session)


@router.get("/ft-training-jobs/{training_job_id}")
def get_ft_training_job(training_job_id: str) -> dict[str, Any]:
    with Session(get_engine()) as session:
        training_job = get_training_job(session, training_job_id)
    if training_job is None:
        raise HTTPException(
            status_code=404, detail="fine-tuning training job not found"
        )
    return training_job


@router.get("/models")
def get_models() -> list[dict[str, Any]]:
    with Session(get_engine()) as session:
        return list_models(session)


@router.get("/models/{model_id}")
def get_model_detail(model_id: str) -> dict[str, Any]:
    with Session(get_engine()) as session:
        model = get_model(session, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="model not found")
    return model


@router.post("/inference/run")
def post_inference_run(
    request: InferenceRunRequest,
    llm_client: LLMClient = Depends(get_llm_client),
) -> dict[str, Any]:
    prompt = request.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt must not be empty")

    with Session(get_engine()) as session:
        try:
            model = resolve_model_selection(
                session,
                model_id=request.model_id,
                ollama_model_name=request.ollama_model_name,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="model not found") from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        retrieval_preview: dict[str, Any] | None = None
        if request.rag_collection_id:
            try:
                retrieval_preview = preview_collection_retrieval(
                    session,
                    collection_id=request.rag_collection_id,
                    query=prompt,
                    top_k=request.top_k,
                )
            except KeyError as exc:
                raise HTTPException(
                    status_code=404, detail="RAG collection not found"
                ) from exc

    context = "No RAG collection selected."
    if retrieval_preview is not None:
        context = (
            "\n\n".join(
                f"[{item['filename']}]\n{item['excerpt']}"
                for item in retrieval_preview.get("results", [])
            )
            or "No matching RAG collection context found."
        )

    try:
        result = llm_client.generate_answer(
            question=prompt,
            context=context,
            model=request.ollama_model_name or model["ollama_model_name"],
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
    except LLMClientError as exc:
        raise HTTPException(
            status_code=502, detail=f"LLM request failed: {exc}"
        ) from exc

    return {
        "answer": result.answer,
        "model": model,
        "meta": {
            "provider": "ollama",
            "model": result.model,
            "used_fallback": result.used_fallback,
            "rag_collection_id": request.rag_collection_id,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        },
        "retrieval_preview": retrieval_preview,
    }
