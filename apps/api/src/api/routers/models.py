from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import threading
import uuid
from typing import Any, Generator, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.config import get_settings
from api.db import get_engine
from api.dependencies import get_llm_client
from api.llm import LLMClient, LLMClientError
from api.models import (
    FTModelArtifactRecord,
    FTTrainingJobRecord,
    ModelRegistryRecord,
)
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


_model_id_cache: dict[str, tuple[str, float]] = {}  # key → (resolved_id, expires_at)
_MODEL_ID_CACHE_TTL = 30.0

# ---------------------------------------------------------------------------
# Polling-based verification job state (mobile/WebKit-safe alternative to SSE)
# ---------------------------------------------------------------------------

_verify_jobs: dict[str, dict] = {}
_verify_jobs_lock = threading.Lock()
_VERIFY_JOB_MAX = 50


def _verify_job_prune() -> None:
    """Discard oldest jobs when over cap. Call with _verify_jobs_lock held."""
    if len(_verify_jobs) > _VERIFY_JOB_MAX:
        to_drop = sorted(_verify_jobs.keys())[: len(_verify_jobs) - _VERIFY_JOB_MAX]
        for k in to_drop:
            _verify_jobs.pop(k, None)


def _run_verify_job(job_id: str, request: VerifyRequest) -> None:
    """Background thread: runs verification, updates _verify_jobs[job_id]."""

    def _set(**kwargs: Any) -> None:
        with _verify_jobs_lock:
            _verify_jobs[job_id].update(kwargs)

    def _log(entry: str) -> None:
        with _verify_jobs_lock:
            _verify_jobs[job_id]["log_entries"].append(entry)

    try:
        _set(status="running")
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

        steps = [
            ("ft_rag",    request.fine_tuned_model, True,  "FT+RAG"),
            ("ft_only",   request.fine_tuned_model, False, "FT-only"),
            ("base_rag",  request.base_model,        True,  "Base+RAG"),
            ("base_only", request.base_model,        False, "Base-only"),
        ]
        answers: dict[str, str] = {}

        for step_num, (skey, model, use_rag, label) in enumerate(steps, start=1):
            _set(step=step_num - 1, label=f"Step {step_num}/5: Loading {model}…")
            _log(f"[{step_num}/5] Loading model: {model}")
            warn = _lmstudio_ensure_loaded(base_url, model)
            if warn:
                _log(f"Warning: {warn}")
            # Log the LM Studio id we'll actually inference against, so the
            # transcript proves which model produced the output.  If the
            # resolved id differs from the requested model (e.g. case-
            # normalised by LM Studio) the user can see it in the log.
            resolved_step = _resolve_lmstudio_model(base_url, model)
            if resolved_step.lower() != str(model).lower():
                _log(f"[{step_num}/5] LM Studio id resolved to: {resolved_step!r}")
            _set(label=f"Step {step_num}/5: {label} inference…")
            _log(f"[{step_num}/5] Running {label} inference (id={resolved_step!r})…")
            ctx = rag_context if use_rag else ""
            try:
                answer = _lmstudio_chat(
                    base_url,
                    model,
                    _inference_messages(request.question, ctx),
                    timeout=120.0,
                    max_tokens=192,
                )
            except Exception as exc:
                answer = f"[Inference error: {exc}]"
                _log(f"Error ({skey}): {exc}")
            answers[skey] = answer
            _set(step=step_num)
            short = answer[:200] + ("…" if len(answer) > 200 else "")
            _log(f"[{skey}] {short}")

        _set(step=4, label=f"Step 5/5: Loading verifier {request.verifier_model}…")
        _log(f"[5/5] Loading verifier: {request.verifier_model}")
        warn = _lmstudio_ensure_loaded(base_url, request.verifier_model)
        if warn:
            _log(f"Warning: {warn}")
        _set(label="Step 5/5: Grading with LLM-as-Judge…")
        _log("[5/5] Grading with LLM-as-Judge…")

        ground_truth_section = (
            f"\nGround truth (knowledge base):\n{rag_context}\n"
            if rag_context
            else "\n(No knowledge base context available.)\n"
        )
        # Pre-replace failed AND degenerate answers with short sentinels so
        # the judge prompt stays small.  Without this, a long degenerate FT
        # output (e.g. 250+ tokens of "? PDFuser PDF PDF") inflates the
        # judge's reasoning pass past its token budget and we lose the
        # grading altogether — including for coherent base answers.
        def _grading_input(value: str) -> str:
            if _is_inference_failure(value):
                return "N/A — inference failed"
            if _is_degenerate_answer(value):
                return "N/A — degenerate / repetitive output"
            return value

        grading_inputs = {k: _grading_input(v) for k, v in answers.items()}
        grading_prompt = _GRADING_TEMPLATE.format(
            question=request.question,
            ground_truth_section=ground_truth_section,
            ft_rag=grading_inputs.get("ft_rag", ""),
            ft_only=grading_inputs.get("ft_only", ""),
            base_rag=grading_inputs.get("base_rag", ""),
            base_only=grading_inputs.get("base_only", ""),
        )

        # Score defaults: None means "not graded" (UI renders "—"), distinct
        # from 0 which means "explicitly failed/degenerate". Without this
        # distinction, a judge timeout was silently flattening coherent base
        # answers to 0, making the run look like the FT *and* base failed.
        default_scores: dict[str, Any] = {
            "ft_rag": None, "ft_only": None, "base_rag": None, "base_only": None,
        }
        default_comments: dict[str, Any] = {
            "ft_rag": "", "ft_only": "", "base_rag": "", "base_only": "",
        }
        grading_error: str | None = None

        try:
            # _judge_chat sizes the token + timeout budget based on whether
            # the judge is a thinking-mode model (Qwen3, DeepSeek-R1).  For
            # thinking models it ships ~5120 tokens / 360s; for plain chat
            # models it ships ~1024 / 180s.  This is what stops a Qwen3
            # judge from running out of budget mid-reasoning and forcing
            # all scores to None.
            raw_grade = _judge_chat(
                base_url, request.verifier_model, grading_prompt,
            )
            grade_data = _parse_judge_json(raw_grade)
            for gkey in ("ft_rag", "ft_only", "base_rag", "base_only"):
                raw_score = grade_data.get("scores", {}).get(gkey)
                if raw_score is None:
                    continue  # leave as None so UI shows "—"
                default_scores[gkey] = max(0, min(10, int(float(raw_score))))
                default_comments[gkey] = str(grade_data.get("comments", {}).get(gkey, ""))
        except Exception as exc:
            grading_error = str(exc)
            _log(f"Grading error: {exc}")

        ft_failures = 0
        ft_total = 0
        for gkey in ("ft_rag", "ft_only", "base_rag", "base_only"):
            ans = answers.get(gkey, "")
            is_ft_variant = gkey.startswith("ft_")
            if is_ft_variant:
                ft_total += 1
            if _is_inference_failure(ans):
                default_scores[gkey] = 0
                default_comments[gkey] = f"[INFERENCE FAILED — score forced to 0] {ans}"
                if is_ft_variant:
                    ft_failures += 1
            elif _is_degenerate_answer(ans):
                default_scores[gkey] = 0
                default_comments[gkey] = f"[DEGENERATE OUTPUT — score forced to 0] {ans[:120]}…"
                if is_ft_variant:
                    ft_failures += 1

        # Resolve the LM Studio model id we actually inferenced against so the
        # UI can prove the FT model was the target (vs e.g. a stale base
        # row).  We use the shared resolver which itself consults the loaded
        # set and is invalidated on every load/unload.
        resolved_ft = _resolve_lmstudio_model(base_url, request.fine_tuned_model)
        resolved_base = _resolve_lmstudio_model(base_url, request.base_model)

        ft_health_warning: str | None = None
        if ft_total and ft_failures == ft_total:
            # Both FT variants failed.  Tell the user this is almost certainly
            # a training-quality issue, not a routing bug.  We also include
            # the resolved LM Studio id so they can see the FT model was
            # genuinely loaded and answered (badly).
            ft_health_warning = (
                "Fine-tuned model produced unusable output on both variants. "
                "This is almost always a training-quality issue (loss diverged, "
                "learning rate too high for the dataset size, or prompt format "
                "mismatch between training data and the model's chat template) "
                "— not a routing problem. "
                f"LM Studio id actually inferenced: {resolved_ft!r}. "
                "Re-train with a larger dataset, lower learning rate, or fewer iters."
            )

        # Surface judge problems separately from FT problems so users can
        # tell "the FT model collapsed" from "the judge model couldn't grade
        # in time".  For any variant the judge failed to score, leave the
        # cell as "—" (None) and write a one-line breadcrumb into the
        # comment so the UI shows *why* there is no score.
        judge_warning: str | None = None
        if grading_error is not None:
            judge_warning = (
                f"Judge model {request.verifier_model!r} failed to grade: "
                f"{grading_error}. Coherent answers are shown without a score "
                "(—) instead of being flattened to 0. Try a smaller / "
                "non-thinking judge model, or rerun verification."
            )
            for gkey in ("ft_rag", "ft_only", "base_rag", "base_only"):
                if default_scores[gkey] is None and not default_comments[gkey]:
                    default_comments[gkey] = "[NOT GRADED — judge model unavailable]"

        # Output-similarity diagnostic: compute word-level Jaccard between
        # FT and base for both RAG modes.  When the similarity is very high,
        # the FT model isn't producing distinguishable output for the question
        # — usually because the training data doesn't cover the topic or the
        # run was undertrained.  This is *not* a routing bug (resolved ids
        # already prove the right model was used); the banner just helps users
        # understand why FT and base look "identical".
        sim_no_rag = _normalized_word_jaccard(
            answers.get("ft_only", ""), answers.get("base_only", "")
        )
        sim_with_rag = _normalized_word_jaccard(
            answers.get("ft_rag", ""), answers.get("base_rag", "")
        )
        SIM_HIGH = 0.85
        ft_similarity_warning: str | None = None
        # Only fire when at least one variant pair is meaningfully similar AND
        # the FT health warning didn't already fire (degenerate output is a
        # different story — the FT *is* different from base, just unusable).
        if (
            ft_health_warning is None
            and (sim_no_rag >= SIM_HIGH or sim_with_rag >= SIM_HIGH)
        ):
            ft_similarity_warning = (
                "Fine-tuned and base models produced near-identical text on "
                f"this question (Jaccard similarity: no-RAG={sim_no_rag:.0%}, "
                f"with-RAG={sim_with_rag:.0%}).  Routing is correct — the FT "
                f"model {resolved_ft!r} was loaded and inferenced — but the "
                "fine-tune is not changing the answer for this query. Two "
                "likely causes: (1) the training data doesn't cover this "
                "topic, so the FT falls back to pretrained knowledge; "
                "(2) the run used too few iters / too low a learning rate to "
                "memorize new facts. Ask a question from your training pairs, "
                "or re-train with more data."
            )

        result = {
            "question": request.question,
            "rag_context": rag_context,
            "answers": answers,
            "scores": default_scores,
            "comments": default_comments,
            "grading_error": grading_error,
            "ft_health_warning": ft_health_warning,
            "judge_warning": judge_warning,
            "ft_similarity_warning": ft_similarity_warning,
            "ft_similarity_to_base": {
                "no_rag": round(sim_no_rag, 3),
                "with_rag": round(sim_with_rag, 3),
            },
            "models": {
                "fine_tuned": request.fine_tuned_model,
                "base": request.base_model,
                "verifier": request.verifier_model,
            },
            "resolved_model_ids": {
                "fine_tuned": resolved_ft,
                "base": resolved_base,
            },
        }
        _log("Verification complete.")
        _set(status="done", step=5, label="Done.", result=result)

    except Exception as exc:
        with _verify_jobs_lock:
            _verify_jobs[job_id].update(status="failed", error=str(exc))


def _resolve_lmstudio_model(base_url: str, model_name: str) -> str:
    """Return the exact model ID from LM Studio, using case-insensitive matching.

    LM Studio normalises loaded model IDs to lowercase while the registry may
    preserve the original casing.  This helper resolves the mismatch by
    consulting `loaded_lmstudio_models` (which has its own 30s TTL cache that
    is already invalidated by `invalidate_loaded_cache()` after every load /
    unload), so we don't keep an independent stale view here.

    A short local cache by (base_url, model_name) is still kept so we don't
    recompute the lowercase / basename matching on every chat call when many
    requests target the same model.  This cache is also cleared whenever the
    underlying loaded set changes, by `invalidate_resolve_cache()`.
    """
    cache_key = f"{base_url}|{model_name}"
    entry = _model_id_cache.get(cache_key)
    if entry and time.monotonic() < entry[1]:
        return entry[0]

    from api.services.model_registry.lmstudio_register import loaded_lmstudio_models

    try:
        loaded = loaded_lmstudio_models(base_url=base_url)
        model_ids: list[str] = list(loaded)
        lower_name = model_name.lower()
        resolved = next((mid for mid in model_ids if mid.lower() == lower_name), None)
        if resolved is None and "/" in lower_name:
            basename = lower_name.rsplit("/", 1)[-1]
            resolved = next((mid for mid in model_ids if mid.lower() == basename), model_name)
        elif resolved is None:
            resolved = model_name
    except Exception:
        resolved = model_name

    _model_id_cache[cache_key] = (resolved, time.monotonic() + _MODEL_ID_CACHE_TTL)
    return resolved


def invalidate_resolve_cache() -> None:
    """Clear the local resolve cache.  Call after `lms load`/`lms unload`
    so a subsequent chat call sees the new loaded set instead of a stale
    pre-load resolution (e.g. case-preserved registry name returned
    instead of the newly-loaded lowercase id)."""
    _model_id_cache.clear()


def _lmstudio_chat(
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    timeout: float = 120.0,
    max_tokens: int | None = None,
    chat_template_kwargs: dict[str, Any] | None = None,
) -> str:
    """Direct LM Studio chat call bypassing the registry.

    `chat_template_kwargs` (optional) is forwarded to LM Studio so callers
    can request features like ``{"enable_thinking": false}`` for Qwen3.
    Only send it for models known to accept it — many non-Qwen models
    return HTTP 400 if the field is present.
    """
    resolved = _resolve_lmstudio_model(base_url, model)
    payload: dict[str, Any] = {"model": resolved, "messages": messages, "temperature": 0}
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if chat_template_kwargs:
        payload["chat_template_kwargs"] = chat_template_kwargs
    response = httpx.post(
        f"{base_url}/chat/completions",
        json=payload,
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


def _is_thinking_capable_model(model_name: str) -> bool:
    """Return True if `model_name` looks like a Qwen3 / DeepSeek-R1 -style
    thinking-mode model that supports ``enable_thinking`` in
    ``chat_template_kwargs``.  Liquid LFM and other non-thinking models
    reject the field with HTTP 400, so gate it carefully.
    """
    lower = model_name.lower()
    return any(p in lower for p in ("qwen3", "qwen-3", "deepseek-r1", "deepseek_r1"))


def _judge_chat(
    base_url: str,
    judge_model: str,
    grading_prompt: str,
    *,
    timeout: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """Grade with `judge_model`. Sizes its budget based on whether the
    judge is a Qwen3 / DeepSeek-R1 -style thinking model.

    Observed against ``qwen3.5-4b-mlx`` on this machine: it ignores
    ``/no_think`` directives and ``chat_template_kwargs.enable_thinking=false``
    and always emits ~3.8k tokens of ``reasoning_content`` before any
    visible ``content``.  So for thinking-capable judges we ship a 5120-
    token / 360 s budget by default — enough to cover the reasoning pass
    plus the short JSON answer — and a much tighter 1024-token / 180 s
    budget for non-thinking judges where the bigger budget would just
    waste wall time.  Callers can still override either explicitly.
    """
    messages = _build_judge_messages(grading_prompt)
    is_thinking = _is_thinking_capable_model(judge_model)
    if max_tokens is None:
        max_tokens = 5120 if is_thinking else 1024
    if timeout is None:
        timeout = 360.0 if is_thinking else 180.0
    return _lmstudio_chat(
        base_url, judge_model, messages, timeout=timeout, max_tokens=max_tokens,
    )


def _build_judge_messages(grading_prompt: str) -> list[dict[str, Any]]:
    """Wrap the grading prompt for /v1/chat/completions.

    Prepends `/no_think` (Qwen3 convention) and a short system message
    that disables reasoning-mode preambles on judge models that honour
    the directive.  Non-Qwen judges ignore it harmlessly.  Without this,
    a Qwen3 thinking-mode judge can burn the entire `max_tokens` budget
    on `reasoning_content`, leaving `content` empty and forcing the
    verify job to discard the grading result.
    """
    return [
        {
            "role": "system",
            "content": (
                "/no_think\n"
                "You are a JSON-only grader.  Respond with a single compact "
                "JSON object — no preamble, no explanation, no markdown fence."
            ),
        },
        {"role": "user", "content": grading_prompt},
    ]


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

Return ONLY a compact valid JSON object — no markdown fences, no preface, no
trailing text.  Keep each comment under 15 words so the response fits in a
reasonable token budget:
{{"scores": {{"ft_rag": <0-10>, "ft_only": <0-10>, "base_rag": <0-10>, "base_only": <0-10>}}, "comments": {{"ft_rag": "<≤15 words>", "ft_only": "<≤15 words>", "base_rag": "<≤15 words>", "base_only": "<≤15 words>"}}}}"""


def _sse_event(data: Any) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _normalized_word_jaccard(a: str, b: str) -> float:
    """Word-level Jaccard similarity in [0, 1].  Empty inputs → 0.0.

    Used to detect when an FT model is producing essentially the same text
    as its base — a strong signal that fine-tuning had no measurable effect
    on the question (either off-distribution data or undertrained).
    Returns 0 when either string is empty / a known sentinel so we don't
    flag normal failure cases as "identical to base".
    """
    if not a or not b:
        return 0.0
    if a.startswith("[Inference error:") or b.startswith("[Inference error:"):
        return 0.0
    # Lowercase, strip punctuation lightly, split on whitespace.
    def _tokenize(s: str) -> set[str]:
        return {t.strip(".,;:!?\"'()[]") for t in s.lower().split() if t.strip(".,;:!?\"'()[]")}
    sa, sb = _tokenize(a), _tokenize(b)
    if not sa or not sb:
        return 0.0
    inter = sa & sb
    union = sa | sb
    return len(inter) / len(union)


def _lmstudio_ensure_loaded(base_url: str, model: str) -> str | None:
    """Try to load `model` in LM Studio if not already loaded. Returns a warning string on failure."""
    from api.services.model_registry.lmstudio_register import (
        invalidate_loaded_cache,
        probe_lmstudio_for_model,
    )
    if probe_lmstudio_for_model(base_url=base_url, model_id=model):
        return None
    lms: str | None = shutil.which("lms")
    if lms is None:
        from pathlib import Path as _Path
        candidate = _Path.home() / ".lmstudio" / "bin" / "lms"
        lms = str(candidate) if candidate.is_file() else None
    if lms is None:
        return f"lms CLI not found; '{model}' may not be loaded"

    # Discover the proper model key via `lms ls --json` so we pass the exact
    # indexedModelIdentifier that lms load requires, matching the same logic
    # used at publish time (_lms_load_model in service.py).
    load_target = model
    try:
        ls_proc = subprocess.run(
            [lms, "ls", "--json"],
            capture_output=True, text=True, timeout=10,
            stdin=subprocess.DEVNULL,
        )
        if ls_proc.returncode == 0:
            try:
                listing = json.loads(ls_proc.stdout)
                if isinstance(listing, list):
                    candidate_lower = model.lower()
                    candidate_basename = candidate_lower.rsplit("/", 1)[-1]
                    for entry in listing:
                        if not isinstance(entry, dict) or entry.get("type") != "llm":
                            continue
                        key = str(entry.get("modelKey") or "").lower()
                        indexed = str(entry.get("indexedModelIdentifier") or "").lower()
                        indexed_basename = indexed.rsplit("/", 1)[-1]
                        if (
                            key == candidate_lower
                            or key == candidate_basename
                            or indexed == candidate_lower
                            or indexed_basename == candidate_basename
                        ):
                            load_target = str(
                                entry.get("modelKey")
                                or entry.get("indexedModelIdentifier")
                                or model
                            )
                            break
            except (json.JSONDecodeError, KeyError):
                pass
    except (subprocess.TimeoutExpired, OSError):
        pass

    try:
        proc = subprocess.run(
            [lms, "load", load_target, "--gpu", "max"],
            capture_output=True, text=True, timeout=120,
            stdin=subprocess.DEVNULL,
        )
        invalidate_loaded_cache()
        invalidate_resolve_cache()
        if proc.returncode != 0:
            return f"lms load '{load_target}' failed: {proc.stderr.strip()[:200]}"
        combined = (proc.stdout + proc.stderr).lower()
        _SOFT_FAIL_MARKERS = ("cannot find a model matching", "select a model", "? select", "›")
        if any(m in combined for m in _SOFT_FAIL_MARKERS):
            snippet = (proc.stdout + proc.stderr).strip()[:200]
            return f"lms load '{load_target}' may have failed (interactive prompt or no-match): {snippet}"
    except (subprocess.TimeoutExpired, OSError) as exc:
        return f"lms load timed out for '{load_target}': {exc}"
    return None


def _is_inference_failure(answer: str) -> bool:
    """Return True if `answer` represents a failed/error inference result."""
    return not answer or answer.startswith("[Inference error:")


def _parse_judge_json(raw_grade: str) -> dict[str, Any]:
    """Parse judge-model response tolerating trailing text after the JSON object."""
    text = raw_grade.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text.strip())
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        obj, _ = json.JSONDecoder().raw_decode(text)
        return obj


def _is_degenerate_answer(answer: str) -> bool:
    """Return True if answer is obviously degenerate — one token repeated many times.

    Uses two signals: very low unique-token ratio (<30%) or a single token
    dominating more than 60% of the output.  Both require at least 6 tokens so
    legitimately short answers are never flagged.
    """
    tokens = answer.split()
    n = len(tokens)
    if n < 6:
        return False
    unique_count = len(set(tokens))
    if unique_count / n < 0.3:
        return True
    top = max(set(tokens), key=tokens.count)
    return tokens.count(top) / n > 0.6


def _verify_sse_stream(request: VerifyRequest) -> Generator[str, None, None]:
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

    steps = [
        ("ft_rag",    request.fine_tuned_model, True,  "FT+RAG inference…"),
        ("ft_only",   request.fine_tuned_model, False, "FT-only inference…"),
        ("base_rag",  request.base_model,        True,  "Base+RAG inference…"),
        ("base_only", request.base_model,        False, "Base-only inference…"),
    ]
    answers: dict[str, str] = {}

    for step_num, (key, model, use_rag, label) in enumerate(steps, start=1):
        yield _sse_event({"type": "progress", "step": step_num, "total": 5, "label": label})
        warn = _lmstudio_ensure_loaded(base_url, model)
        if warn:
            yield _sse_event({"type": "warning", "message": warn})
        ctx = rag_context if use_rag else ""
        try:
            answer = _lmstudio_chat(
                base_url, model, _inference_messages(request.question, ctx), max_tokens=192
            )
        except Exception as exc:
            answer = f"[Inference error: {exc}]"
        answers[key] = answer
        yield _sse_event({"type": "answer", "key": key, "answer": answer})

    yield _sse_event({"type": "progress", "step": 5, "total": 5, "label": "Grading with LLM-as-Judge…"})
    warn = _lmstudio_ensure_loaded(base_url, request.verifier_model)
    if warn:
        yield _sse_event({"type": "warning", "message": warn})

    ground_truth_section = (
        f"\nGround truth (knowledge base):\n{rag_context}\n"
        if rag_context
        else "\n(No knowledge base context available.)\n"
    )
    # Replace failed answers with a sentinel so the verifier never scores error text.
    grading_inputs = {
        k: ("N/A — inference failed" if _is_inference_failure(v) else v)
        for k, v in answers.items()
    }
    grading_prompt = _GRADING_TEMPLATE.format(
        question=request.question,
        ground_truth_section=ground_truth_section,
        ft_rag=grading_inputs.get("ft_rag", ""),
        ft_only=grading_inputs.get("ft_only", ""),
        base_rag=grading_inputs.get("base_rag", ""),
        base_only=grading_inputs.get("base_only", ""),
    )

    # None = "not graded" (UI renders "—"), distinct from 0 = explicitly
    # failed/degenerate. Kept in sync with _run_verify_job / the JSON path.
    default_scores: dict[str, Any] = {
        "ft_rag": None, "ft_only": None, "base_rag": None, "base_only": None,
    }
    default_comments: dict[str, Any] = {"ft_rag": "", "ft_only": "", "base_rag": "", "base_only": ""}
    grading_error: str | None = None

    try:
        # Use _judge_chat (not raw _lmstudio_chat): it adds the /no_think
        # system prompt and sizes the token/timeout budget for thinking-mode
        # judges (Qwen3, DeepSeek-R1), which otherwise burn the budget on
        # reasoning_content and force every score to None.
        raw_grade = _judge_chat(base_url, request.verifier_model, grading_prompt)
        grade_data = _parse_judge_json(raw_grade)
        for key in ("ft_rag", "ft_only", "base_rag", "base_only"):
            raw_score = grade_data.get("scores", {}).get(key)
            if raw_score is None:
                continue  # leave as None so the UI shows "—"
            default_scores[key] = max(0, min(10, int(float(raw_score))))
            default_comments[key] = str(grade_data.get("comments", {}).get(key, ""))
    except Exception as exc:
        grading_error = str(exc)

    # Hard-enforce score=0 for inference failures and degenerate (repetitive) outputs.
    for key in ("ft_rag", "ft_only", "base_rag", "base_only"):
        ans = answers.get(key, "")
        if _is_inference_failure(ans):
            default_scores[key] = 0
            default_comments[key] = f"[INFERENCE FAILED — score forced to 0] {ans}"
        elif _is_degenerate_answer(ans):
            default_scores[key] = 0
            default_comments[key] = f"[DEGENERATE OUTPUT — score forced to 0] {ans[:120]}…"

    yield _sse_event({
        "type": "result",
        "question": request.question,
        "rag_context": rag_context,
        "answers": answers,
        "scores": default_scores,
        "comments": default_comments,
        "grading_error": grading_error,
        "models": {
            "fine_tuned": request.fine_tuned_model,
            "base": request.base_model,
            "verifier": request.verifier_model,
        },
    })


@router.get("/inference/verify-health")
def get_inference_verify_health(
    ft_model: str = "",
    base_model: str = "",
    judge_model: str = "",
) -> dict[str, Any]:
    """Fast probe: checks model resolution + LM Studio load status without running inference.

    Query params (all optional):
      ft_model, base_model, judge_model — model IDs to probe

    Returns per-model resolution and probe status, plus the full loaded-models set.
    Used to confirm: (1) service runs latest code, (2) model IDs resolve correctly,
    (3) ensure_loaded would return no warning for the given model IDs.
    """
    from api.services.model_registry.lmstudio_register import (
        invalidate_loaded_cache,
        loaded_lmstudio_models,
        probe_lmstudio_for_model,
    )

    settings = get_settings()
    base_url = settings.lmstudio_base_url
    invalidate_loaded_cache()  # always fetch fresh for this health check
    loaded = sorted(loaded_lmstudio_models(base_url=base_url))

    def _check(model_id: str) -> dict[str, Any]:
        if not model_id:
            return {"input": model_id, "resolved": None, "probe": None, "warn": None}
        resolved = _resolve_lmstudio_model(base_url, model_id)
        probed = probe_lmstudio_for_model(base_url=base_url, model_id=model_id)
        warn: str | None = None
        if not probed:
            import shutil as _shutil
            lms_bin = _shutil.which("lms")
            if lms_bin is None:
                from pathlib import Path as _Path
                candidate = _Path.home() / ".lmstudio" / "bin" / "lms"
                lms_bin = str(candidate) if candidate.is_file() else None
            warn = (
                "model is loaded — ensure_loaded would return no warning"
                if probed
                else f"model NOT found in LM Studio; ensure_loaded would attempt lms load (lms={'found' if lms_bin else 'NOT FOUND'})"
            )
        return {
            "input": model_id,
            "resolved": resolved,
            "resolution_changed": resolved != model_id,
            "probe": probed,
            "warn": warn,
        }

    return {
        "code_version": "v19-robust-judge-json",
        "lmstudio_base_url": base_url,
        "lmstudio_loaded": loaded,
        "models": {
            "ft_model": _check(ft_model),
            "base_model": _check(base_model),
            "judge_model": _check(judge_model),
        },
        "failure_scoring": "inference errors → score=0 via _is_inference_failure(); repetitive/degenerate outputs → score=0 via _is_degenerate_answer()",
    }


@router.post("/inference/verify")
def post_inference_verify(request: VerifyRequest, req: Request) -> Any:
    accept = req.headers.get("accept", "")
    if "text/event-stream" in accept:
        return StreamingResponse(
            _verify_sse_stream(request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # JSON fallback path
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
        _lmstudio_ensure_loaded(base_url, model)
        ctx = rag_context if use_rag else ""
        try:
            return _lmstudio_chat(
                base_url, model, _inference_messages(request.question, ctx), max_tokens=192
            )
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
    answers_map = {"ft_rag": ft_rag, "ft_only": ft_only, "base_rag": base_rag, "base_only": base_only}
    # Pre-replace failed AND degenerate answers with short sentinels so the
    # judge prompt stays compact (long degenerate outputs blow up the
    # judge's reasoning budget; see _run_verify_job comment).
    def _grading_input_fallback(value: str) -> str:
        if _is_inference_failure(value):
            return "N/A — inference failed"
        if _is_degenerate_answer(value):
            return "N/A — degenerate / repetitive output"
        return value
    grading_inputs = {k: _grading_input_fallback(v) for k, v in answers_map.items()}
    grading_prompt = _GRADING_TEMPLATE.format(
        question=request.question,
        ground_truth_section=ground_truth_section,
        ft_rag=grading_inputs["ft_rag"],
        ft_only=grading_inputs["ft_only"],
        base_rag=grading_inputs["base_rag"],
        base_only=grading_inputs["base_only"],
    )

    # Score defaults match the verify-job path: None = "not graded" (UI
    # renders "—"), distinct from 0 = "explicitly failed/degenerate".
    default_scores: dict[str, Any] = {"ft_rag": None, "ft_only": None, "base_rag": None, "base_only": None}
    default_comments: dict[str, Any] = {"ft_rag": "", "ft_only": "", "base_rag": "", "base_only": ""}
    grading_error: str | None = None

    _lmstudio_ensure_loaded(base_url, request.verifier_model)
    try:
        raw_grade = _judge_chat(base_url, request.verifier_model, grading_prompt)
        grade_data = _parse_judge_json(raw_grade)
        for key in ("ft_rag", "ft_only", "base_rag", "base_only"):
            raw_score = grade_data.get("scores", {}).get(key)
            if raw_score is None:
                continue
            default_scores[key] = max(0, min(10, int(float(raw_score))))
            default_comments[key] = str(grade_data.get("comments", {}).get(key, ""))
    except Exception as exc:
        grading_error = str(exc)

    # Hard-enforce score=0 for inference failures and degenerate (repetitive) outputs.
    for key in ("ft_rag", "ft_only", "base_rag", "base_only"):
        ans = answers_map.get(key, "")
        if _is_inference_failure(ans):
            default_scores[key] = 0
            default_comments[key] = f"[INFERENCE FAILED — score forced to 0] {ans}"
        elif _is_degenerate_answer(ans):
            default_scores[key] = 0
            default_comments[key] = f"[DEGENERATE OUTPUT — score forced to 0] {ans[:120]}…"

    # Synthetic comment for any variant the judge failed to score so the
    # UI explains the empty cell instead of looking like a silent zero.
    judge_warning: str | None = None
    if grading_error is not None:
        judge_warning = (
            f"Judge model {request.verifier_model!r} failed to grade: "
            f"{grading_error}. Coherent answers shown without a score (—)."
        )
        for key in ("ft_rag", "ft_only", "base_rag", "base_only"):
            if default_scores[key] is None and not default_comments[key]:
                default_comments[key] = "[NOT GRADED — judge model unavailable]"

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
        "judge_warning": judge_warning,
        "models": {
            "fine_tuned": request.fine_tuned_model,
            "base": request.base_model,
            "verifier": request.verifier_model,
        },
    }


@router.post("/inference/verify-job", status_code=202)
def post_inference_verify_job(request: VerifyRequest) -> dict[str, Any]:
    """Start a background verification job; returns job_id immediately for polling.

    Mobile/WebKit-safe: no streaming required.  Poll GET /inference/verify-job/{job_id}.
    """
    job_id = str(uuid.uuid4())
    with _verify_jobs_lock:
        _verify_jobs[job_id] = {
            "job_id": job_id,
            "status": "pending",
            "step": 0,
            "total": 5,
            "label": "Queued…",
            "log_entries": [],
            "result": None,
            "error": None,
        }
        _verify_job_prune()
    t = threading.Thread(target=_run_verify_job, args=(job_id, request), daemon=True)
    t.start()
    return {"job_id": job_id}


@router.get("/inference/verify-job/{job_id}")
def get_inference_verify_job(job_id: str) -> dict[str, Any]:
    """Poll verification job: status, step, label, log_entries, result, error."""
    with _verify_jobs_lock:
        job = _verify_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="verification job not found")
    return dict(job)


@router.delete("/models/{model_id}")
def delete_model(model_id: str) -> dict[str, Any]:
    """Delete a fine-tuned model: unload from LM Studio, remove files from disk, purge registry."""
    from pathlib import Path as _Path

    settings = get_settings()

    with Session(get_engine()) as session:
        model = session.get(ModelRegistryRecord, model_id)
        if model is None:
            raise HTTPException(status_code=404, detail="model not found")

        if model.source_type != "fine_tuned":
            raise HTTPException(
                status_code=400,
                detail="only fine-tuned models can be deleted; base models are managed by LM Studio",
            )

        serving_name = (model.serving_model_name or "").strip()
        published_name = (model.published_model_name or "").strip()

        # 1. Unload from LM Studio
        lms: str | None = shutil.which("lms")
        if lms is None:
            candidate = _Path.home() / ".lmstudio" / "bin" / "lms"
            lms = str(candidate) if candidate.is_file() else None

        if lms and serving_name:
            # LM Studio exposes loaded models with lowercased IDs while the
            # registry preserves case.  Resolve the exact loaded id first so
            # `lms unload` finds the model.  If we can't resolve, fall back to
            # the registry name (with --exact when supported) and lastly to
            # `lms unload --all` as a best-effort sweep.
            loaded_id = _resolve_lmstudio_model(
                settings.lmstudio_base_url.rstrip("/"),
                serving_name,
            )
            unload_targets = []
            if loaded_id and loaded_id.lower() != serving_name.lower():
                unload_targets.append(loaded_id)
            unload_targets.append(serving_name)
            unload_targets.append(serving_name.lower())
            seen: set[str] = set()
            for target in unload_targets:
                if not target or target in seen:
                    continue
                seen.add(target)
                try:
                    subprocess.run(
                        [lms, "unload", target],
                        capture_output=True, text=True, timeout=30,
                        stdin=subprocess.DEVNULL,
                    )
                except (subprocess.TimeoutExpired, OSError):
                    pass

        # Invalidate caches so the deleted model vanishes from /v1/models and
        # the model-ID resolution cache immediately rather than waiting 30s.
        from api.services.model_registry.lmstudio_register import invalidate_loaded_cache
        invalidate_loaded_cache()
        _model_id_cache.clear()

        # 2. Delete model files from LM Studio directory
        models_dir = _Path.home() / ".lmstudio" / "models"
        deleted_paths: list[str] = []

        if published_name and "/" in published_name:
            model_dir = models_dir / published_name
            if model_dir.exists():
                shutil.rmtree(model_dir, ignore_errors=True)
                deleted_paths.append(str(model_dir))

        # Also try the serving_name (short form)
        if serving_name:
            candidates = list(models_dir.glob(f"**/{serving_name}"))
            for candidate in candidates:
                if candidate.is_dir() and str(candidate) not in deleted_paths:
                    shutil.rmtree(candidate, ignore_errors=True)
                    deleted_paths.append(str(candidate))

        # 3. Delete training output directory from the training job
        training_job = None
        if model.artifact_id:
            artifact = session.get(FTModelArtifactRecord, model.artifact_id)
            if artifact:
                training_job = session.get(FTTrainingJobRecord, artifact.training_job_id)

        if training_job and training_job.output_dir:
            output_dir = _Path(training_job.output_dir)
            if output_dir.exists():
                shutil.rmtree(output_dir, ignore_errors=True)
                deleted_paths.append(str(output_dir))

        # 4. Delete the registry entry FIRST (FK points FROM here TO artifacts)
        display_name = model.display_name
        artifact_id_snapshot = model.artifact_id
        session.delete(model)
        session.flush()  # write model deletion to DB before removing artifact rows

        # 5. Delete related artifacts and training job (now safe — FK reference gone)
        if artifact_id_snapshot:
            artifact = session.get(FTModelArtifactRecord, artifact_id_snapshot)
            if artifact:
                # Delete all artifacts for this training job
                session.execute(
                    FTModelArtifactRecord.__table__.delete().where(
                        FTModelArtifactRecord.training_job_id == artifact.training_job_id
                    )
                )
                session.flush()  # ensure artifact rows gone before training_job delete
                # Delete the training job — FK: ft_training_jobs.backing_job_id → jobs.id
                # so FTTrainingJobRecord must be deleted (and flushed) before JobRecord.
                if training_job:
                    backing_job_id = training_job.backing_job_id
                    session.delete(training_job)
                    session.flush()
                    if backing_job_id:
                        from api.models import JobRecord
                        job_rec = session.get(JobRecord, backing_job_id)
                        if job_rec:
                            session.delete(job_rec)

        session.commit()

    return {
        "deleted": True,
        "model_id": model_id,
        "display_name": display_name,
        "deleted_paths": deleted_paths,
    }
