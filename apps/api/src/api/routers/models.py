from __future__ import annotations

import json
import re
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from api.config import get_settings
from api.db import get_engine
from api.dependencies import get_llm_client
from api.llm import LLMClient, LLMClientError
from api.services.model_registry import (
    create_training_job,
    get_model,
    get_model_artifact,
    get_model_lineage,
    get_training_job,
    get_training_job_logs,
    list_models,
    list_training_jobs,
    publish_training_job_artifacts,
    resolve_model_selection,
)
from api.services.rag.collections import preview_collection_retrieval

router = APIRouter(tags=["models"])


class CreateTrainingJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_version_id: str = Field(min_length=1)
    base_model_name: str = Field(min_length=1)
    # Only `sft_qlora` is a real training method. The `deterministic_smoke`
    # path is a trainer backend, not a method — switch backends via the
    # FT_TRAINER_BACKEND env (see services/fine_tuning/trainer.py).
    training_method: Literal["sft_qlora"] = Field(default="sft_qlora")
    hyperparams_json: dict[str, Any] = Field(default_factory=dict)


class InferenceRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1)
    model_id: str | None = None
    serving_model_name: str | None = None
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


@router.get("/ft-training-jobs/{training_job_id}/logs")
def get_ft_training_job_logs(training_job_id: str) -> dict[str, Any]:
    with Session(get_engine()) as session:
        payload = get_training_job_logs(session, training_job_id)
    if payload is None:
        raise HTTPException(
            status_code=404, detail="fine-tuning training job not found"
        )
    return payload


@router.post("/ft-training-jobs/{training_job_id}/publish")
def post_ft_training_job_publish(training_job_id: str) -> dict[str, Any]:
    with Session(get_engine()) as session:
        try:
            return publish_training_job_artifacts(session, training_job_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="fine-tuning training job not found"
            ) from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


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


@router.get("/models/{model_id}/lineage")
def get_model_detail_lineage(model_id: str) -> dict[str, Any]:
    with Session(get_engine()) as session:
        lineage = get_model_lineage(session, model_id)
    if lineage is None:
        raise HTTPException(status_code=404, detail="model not found")
    return lineage


@router.get("/ft-model-artifacts/{artifact_id}")
def get_ft_model_artifact_detail(artifact_id: str) -> dict[str, Any]:
    with Session(get_engine()) as session:
        artifact = get_model_artifact(session, artifact_id)
    if artifact is None:
        raise HTTPException(
            status_code=404, detail="fine-tuning model artifact not found"
        )
    return artifact


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
                serving_model_name=request.serving_model_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
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
            model=str(model["serving_model_name"]),
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
            "provider": "lmstudio",
            "model": result.model,
            "used_fallback": result.used_fallback,
            "rag_collection_id": request.rag_collection_id,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        },
        "retrieval_preview": retrieval_preview,
    }


class VerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verifier_model: str = Field(min_length=1)
    fine_tuned_model: str = Field(min_length=1)
    question: str = Field(min_length=1)
    base_model: str = Field(min_length=1)
    rag_collection_id: str | None = None


def _lmstudio_chat(
    base_url: str, model: str, messages: list[dict[str, Any]], timeout: float = 120.0
) -> str:
    """Direct LM Studio chat call bypassing the registry."""
    response = httpx.post(
        f"{base_url}/chat/completions",
        json={"model": model, "messages": messages, "temperature": 0},
        timeout=httpx.Timeout(connect=5.0, read=timeout, write=timeout, pool=5.0),
    )
    response.raise_for_status()
    payload = response.json()
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("no choices in LM Studio response")
    msg = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
    content = str(msg.get("content") or "").strip()
    if not content:
        reasoning = msg.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning.strip():
            raise ValueError("model ran out of tokens during reasoning pass — increase max_tokens")
        raise ValueError("empty content in LM Studio response")
    return content


def _inference_messages(question: str, rag_context: str) -> list[dict[str, Any]]:
    user_content = (
        f"Context:\n{rag_context}\n\nQuestion: {question}" if rag_context else question
    )
    return [
        {
            "role": "system",
            "content": (
                "Answer the user's question concisely. "
                "If the Context block contains relevant evidence, ground your answer in it."
            ),
        },
        {"role": "user", "content": user_content},
    ]


_GRADING_TEMPLATE = """\
You are an objective LLM-as-Judge. Score 4 AI answers to the same question from 0 to 10.

Question: {question}
{ground_truth_section}
Answers to evaluate:

[ft_rag] Fine-tuned model WITH knowledge base:
{ft_rag}

[ft_only] Fine-tuned model WITHOUT knowledge base:
{ft_only}

[base_rag] Base model WITH knowledge base:
{base_rag}

[base_only] Base model WITHOUT knowledge base:
{base_only}

Scoring rubric (0-10 per answer):
- 9-10: Factually accurate, directly answers the question, complete, no hallucinations
- 7-8: Mostly accurate, minor gaps or slight imprecision
- 5-6: Partially correct, some inaccuracies or missing key details
- 3-4: Tangential or significant errors
- 1-2: Mostly wrong or irrelevant
- 0: No attempt or entirely wrong

Return ONLY valid JSON with no markdown fences and no text outside the JSON object:
{{"scores": {{"ft_rag": <0-10>, "ft_only": <0-10>, "base_rag": <0-10>, "base_only": <0-10>}}, "comments": {{"ft_rag": "<1-2 sentence judgment>", "ft_only": "<1-2 sentence judgment>", "base_rag": "<1-2 sentence judgment>", "base_only": "<1-2 sentence judgment>"}}}}"""


@router.post("/inference/verify")
def post_inference_verify(request: VerifyRequest) -> dict[str, Any]:
    settings = get_settings()
    base_url = settings.lmstudio_base_url

    rag_context = ""
    if request.rag_collection_id:
        with Session(get_engine()) as session:
            try:
                retrieval = preview_collection_retrieval(
                    session,
                    collection_id=request.rag_collection_id,
                    query=request.question,
                    top_k=5,
                )
                rag_context = (
                    "\n\n".join(
                        f"[{item['filename']}]\n{item['excerpt']}"
                        for item in retrieval.get("results", [])
                    )
                    or ""
                )
            except KeyError:
                pass

    def run_one(model: str, use_rag: bool) -> str:
        ctx = rag_context if use_rag else ""
        try:
            return _lmstudio_chat(base_url, model, _inference_messages(request.question, ctx))
        except Exception as exc:
            return f"[Inference error: {exc}]"

    ft_rag = run_one(request.fine_tuned_model, True)
    ft_only = run_one(request.fine_tuned_model, False)
    base_rag = run_one(request.base_model, True)
    base_only = run_one(request.base_model, False)

    ground_truth_section = (
        f"\nGround truth (knowledge base):\n{rag_context}\n"
        if rag_context
        else "\n(No knowledge base context available.)\n"
    )
    grading_prompt = _GRADING_TEMPLATE.format(
        question=request.question,
        ground_truth_section=ground_truth_section,
        ft_rag=ft_rag,
        ft_only=ft_only,
        base_rag=base_rag,
        base_only=base_only,
    )

    default_scores: dict[str, Any] = {"ft_rag": 0, "ft_only": 0, "base_rag": 0, "base_only": 0}
    default_comments: dict[str, Any] = {"ft_rag": "", "ft_only": "", "base_rag": "", "base_only": ""}
    grading_error: str | None = None

    try:
        raw_grade = _lmstudio_chat(
            base_url,
            request.verifier_model,
            [{"role": "user", "content": grading_prompt}],
            timeout=300.0,
        )
        raw_grade = raw_grade.strip()
        if raw_grade.startswith("```"):
            raw_grade = re.sub(r"^```[a-zA-Z]*\n?", "", raw_grade)
            raw_grade = re.sub(r"\n?```$", "", raw_grade.strip())
        grade_data = json.loads(raw_grade)
        for key in ("ft_rag", "ft_only", "base_rag", "base_only"):
            raw_score = grade_data.get("scores", {}).get(key, 0)
            default_scores[key] = max(0, min(10, int(float(raw_score))))
            default_comments[key] = str(grade_data.get("comments", {}).get(key, ""))
    except Exception as exc:
        grading_error = str(exc)

    return {
        "question": request.question,
        "rag_context": rag_context,
        "answers": {
            "ft_rag": ft_rag,
            "ft_only": ft_only,
            "base_rag": base_rag,
            "base_only": base_only,
        },
        "scores": default_scores,
        "comments": default_comments,
        "grading_error": grading_error,
        "models": {
            "fine_tuned": request.fine_tuned_model,
            "base": request.base_model,
            "verifier": request.verifier_model,
        },
    }
