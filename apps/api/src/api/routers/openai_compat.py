from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from api.db import get_engine
from api.dependencies import get_llm_client
from api.llm import LLMClient, LLMClientError, LMStudioChatClient
from api.services.model_registry import list_models
from api.services.rag.collections import preview_collection_retrieval

router = APIRouter(prefix="/v1", tags=["openai-compat"])

OWNED_BY = "domain-adaptable-ai-platform"


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: Literal["system", "user", "assistant", "tool", "developer"]
    content: str | None = None


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str = Field(min_length=1)
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float = Field(default=0, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)
    stream: bool = False
    rag_collection_id: str | None = None
    top_k: int = Field(default=4, ge=1, le=10)


def _is_selectable(model: dict[str, Any]) -> bool:
    readiness = model.get("readiness") or {}
    return bool(readiness.get("selectable"))


def _model_tags(model: dict[str, Any]) -> set[str]:
    tags = model.get("tags_json") or []
    return {str(tag).strip().lower() for tag in tags if str(tag).strip()}


def _friendly_model_name(raw_name: str | None) -> str:
    if not raw_name:
        return "Unknown model"
    base = raw_name.split(":", 1)[0]
    if base.lower().startswith("qwen"):
        base = base.replace("qwen", "Qwen", 1)
    size = ""
    if ":" in raw_name:
        variant = raw_name.split(":", 1)[1]
        head = variant.split("-", 1)[0]
        if head:
            size = f" {head.upper()}"
    return f"{base}{size}".strip()


def _exposed_model_id(model: dict[str, Any]) -> str:
    tags = _model_tags(model)
    friendly = _friendly_model_name(
        str(model.get("serving_model_name") or "")
    )
    if "default" in tags:
        return f"{friendly} - default platform model"
    if "fallback" in tags:
        return f"{friendly} - fallback platform model"
    label = str(model.get("display_name") or model.get("id") or friendly).strip()
    return f"{label} - platform model"


def _model_sort_key(model: dict[str, Any]) -> tuple[int, str]:
    tags = _model_tags(model)
    if "default" in tags:
        priority = 0
    elif "fallback" in tags:
        priority = 1
    else:
        priority = 2
    return (priority, _exposed_model_id(model))


def _build_prompt(messages: list[ChatMessage]) -> tuple[str, str]:
    last_user_idx: int | None = None
    for idx in range(len(messages) - 1, -1, -1):
        if messages[idx].role == "user":
            last_user_idx = idx
            break
    if last_user_idx is None:
        raise HTTPException(
            status_code=400,
            detail="chat completion requires at least one user message",
        )
    question_msg = messages[last_user_idx]
    question = (question_msg.content or "").strip()
    if not question:
        raise HTTPException(
            status_code=400,
            detail="last user message must have non-empty content",
        )

    context_parts: list[str] = []
    for idx, message in enumerate(messages):
        if idx == last_user_idx:
            continue
        content = (message.content or "").strip()
        if not content:
            continue
        context_parts.append(f"[{message.role}]\n{content}")
    context = "\n\n".join(context_parts) or "No prior context provided."
    return question, context


def _resolve_selectable_model(session: Session, requested_model: str) -> dict[str, Any]:
    requested = requested_model.strip()
    if not requested:
        raise HTTPException(status_code=400, detail="model must be provided")

    models = list_models(session)
    by_id = {str(model["id"]): model for model in models if model.get("id")}
    # `list_models` returns newest-first. Multiple fine-tuned rows can
    # share a `display_name` (and thus exposed_id), e.g. two training
    # runs of the same dataset version. Build the dict in two passes so
    # the *selectable* one wins when present; otherwise fall back to
    # the newest non-selectable. Without this, a stale failed-publish
    # row from an earlier session can win and the chat call dies with
    # "fine-tuned model publish preparation failed" even though a
    # working sibling is loaded in LM Studio.
    by_exposed_id: dict[str, dict[str, Any]] = {}
    for model in models:  # newest first
        key = _exposed_model_id(model)
        if key not in by_exposed_id:
            by_exposed_id[key] = model
    for model in models:  # override with a selectable sibling if any
        if _is_selectable(model):
            by_exposed_id[_exposed_model_id(model)] = model
    if requested in by_exposed_id:
        model = by_exposed_id[requested]
        if not _is_selectable(model):
            readiness = model.get("readiness") or {}
            raise HTTPException(
                status_code=404,
                detail=str(
                    readiness.get("selectable_reason")
                    or "model is not runtime-ready/selectable"
                ),
            )
        return model

    if requested in by_id:
        model = by_id[requested]
        if not _is_selectable(model):
            readiness = model.get("readiness") or {}
            raise HTTPException(
                status_code=404,
                detail=str(
                    readiness.get("selectable_reason")
                    or "model is not runtime-ready/selectable"
                ),
            )
        return model

    matches_by_serving = [
        model
        for model in models
        if model.get("serving_model_name") == requested
        or model.get("published_model_name") == requested
    ]
    if not matches_by_serving:
        raise HTTPException(
            status_code=404,
            detail=(
                "model not found in registry; the OpenAI-compatible shim only exposes "
                "registry-tracked runtime-ready/selectable models"
            ),
        )
    selectable_match = next(
        (model for model in matches_by_serving if _is_selectable(model)),
        None,
    )
    if selectable_match is None:
        readiness = (matches_by_serving[0].get("readiness") or {})
        raise HTTPException(
            status_code=404,
            detail=str(
                readiness.get("selectable_reason")
                or "model is not runtime-ready/selectable"
            ),
        )
    return selectable_match


@router.get("/models")
def list_v1_models() -> dict[str, Any]:
    with Session(get_engine()) as session:
        models = list_models(session)
    now = int(time.time())
    data = [
        {
            "id": _exposed_model_id(model),
            "object": "model",
            "created": now,
            "owned_by": OWNED_BY,
            "registry_id": model.get("id"),
            "display_name": model.get("display_name"),
            "serving_model_name": model.get("serving_model_name"),
            "source_type": model.get("source_type"),
            "readiness": model.get("readiness"),
        }
        for model in sorted(models, key=_model_sort_key)
        if _is_selectable(model)
    ]
    return {"object": "list", "data": data}


def _run_chat_completion(
    request: ChatCompletionRequest,
    llm_client: LLMClient,
) -> tuple[dict[str, Any], str, str, int]:
    with Session(get_engine()) as session:
        model = _resolve_selectable_model(session, request.model)

    question, context = _build_prompt(request.messages)

    retrieval_preview: dict[str, Any] | None = None
    if request.rag_collection_id:
        with Session(get_engine()) as session:
            try:
                retrieval_preview = preview_collection_retrieval(
                    session,
                    collection_id=request.rag_collection_id,
                    query=question,
                    top_k=request.top_k,
                )
            except KeyError as exc:
                raise HTTPException(
                    status_code=404, detail="RAG collection not found"
                ) from exc
        rag_context = (
            "\n\n".join(
                f"[{item['filename']}]\n{item['excerpt']}"
                for item in retrieval_preview.get("results", [])
            )
            or "No matching RAG collection context found."
        )
        context = (
            f"{context}\n\n"
            "Use the following platform RAG collection evidence when it is relevant. "
            "If it is insufficient, say so.\n\n"
            f"{rag_context}"
        )

    serving_model_name = model.get("serving_model_name")
    if not serving_model_name:
        raise HTTPException(
            status_code=409,
            detail=(
                "selected model has no serving target; only runtime-ready/selectable "
                "models can be used through the OpenAI-compatible shim"
            ),
        )

    try:
        result = llm_client.generate_answer(
            question=question,
            context=context,
            model=str(serving_model_name),
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
    except LLMClientError as exc:
        raise HTTPException(
            status_code=502, detail=f"LLM request failed: {exc}"
        ) from exc

    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    exposed_model_id = _exposed_model_id(model) if model.get("id") else str(
        serving_model_name
    )
    response = {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": exposed_model_id,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": result.answer},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        "x_domain_platform": {
            "registry_model_id": model.get("id"),
            "serving_model_name": serving_model_name,
            "used_fallback": result.used_fallback,
            "actual_model": result.model,
            "source_type": model.get("source_type"),
            "readiness": model.get("readiness"),
            "rag_collection_id": request.rag_collection_id,
            "retrieval_preview": retrieval_preview,
            "notes": [
                "Token counts are placeholders; LM Studio's OpenAI shim does not report usage.",
                "RAG-collection grounding is opt-in via rag_collection_id; ordinary OpenAI clients that do not send it remain plain chat.",
            ],
        },
    }
    return response, completion_id, exposed_model_id, created


def _build_lmstudio_messages(
    *, question: str, context: str
) -> list[dict[str, Any]]:
    return [
        {
            "role": "system",
            "content": (
                "Answer the user's question concisely. If the Context block "
                "contains relevant evidence, ground your answer in it; "
                "otherwise rely on your own knowledge."
            ),
        },
        {
            "role": "user",
            "content": f"Context:\n{context}\n\nQuestion: {question}",
        },
    ]


def _stream_via_lmstudio(
    *,
    llm_client: LLMClient,
    question: str,
    context: str,
    serving_model_name: str,
    temperature: float,
    max_tokens: int | None,
    completion_id: str,
    exposed_model_id: str,
    created: int,
    platform_meta: dict[str, Any],
) -> Iterator[str]:
    if not isinstance(llm_client, LMStudioChatClient):
        # Fall back to buffered single-chunk SSE for non-streaming clients.
        yield from _stream_chat_completion(
            {
                "choices": [{"message": {"content": ""}}],
                "x_domain_platform": platform_meta,
            },
            completion_id,
            exposed_model_id,
            created,
        )
        return

    try:
        upstream_iter = llm_client.stream_chat_messages(
            messages=_build_lmstudio_messages(question=question, context=context),
            model=serving_model_name,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        for chunk in upstream_iter:
            # Rewrite the upstream id+model so external clients see the
            # platform's exposed identifiers, not LM Studio's raw model id.
            chunk = dict(chunk)
            chunk["id"] = completion_id
            chunk["model"] = exposed_model_id
            chunk["created"] = created
            # system_fingerprint leaks the upstream serving name; strip it
            # so all client-facing identifiers stay platform-owned.
            chunk.pop("system_fingerprint", None)
            # Thinking-mode models (Qwen3, DeepSeek-R1) stream tokens in
            # `reasoning_content` and leave `content` empty until the
            # reasoning pass ends. Most OpenAI-compatible clients only
            # render `content`, so mirror reasoning tokens into a
            # `content` field while the model is still thinking. The
            # final assistant message (after the reasoning pass) lands in
            # `content` natively and overwrites this on its own chunk.
            choices = chunk.get("choices")
            if isinstance(choices, list):
                for choice in choices:
                    if not isinstance(choice, dict):
                        continue
                    delta = choice.get("delta")
                    if not isinstance(delta, dict):
                        continue
                    content = delta.get("content")
                    reasoning = delta.get("reasoning_content")
                    if (
                        (not isinstance(content, str) or not content)
                        and isinstance(reasoning, str)
                        and reasoning
                    ):
                        delta["content"] = reasoning
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
    except LLMClientError as exc:
        error_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": exposed_model_id,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": f"\n[stream error: {exc}]"},
                    "finish_reason": "stop",
                }
            ],
        }
        yield f"data: {json.dumps(error_chunk, ensure_ascii=False)}\n\n"

    final_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": exposed_model_id,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        "x_domain_platform": platform_meta,
    }
    yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


def _stream_chat_completion(
    response: dict[str, Any],
    completion_id: str,
    exposed_model_id: str,
    created: int,
) -> Iterator[str]:
    content = response["choices"][0]["message"]["content"] or ""
    first_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": exposed_model_id,
        "choices": [
            {"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}
        ],
    }
    yield f"data: {json.dumps(first_chunk, ensure_ascii=False)}\n\n"

    if content:
        content_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": exposed_model_id,
            "choices": [
                {"index": 0, "delta": {"content": content}, "finish_reason": None}
            ],
        }
        yield f"data: {json.dumps(content_chunk, ensure_ascii=False)}\n\n"

    final_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": exposed_model_id,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        "x_domain_platform": response["x_domain_platform"],
    }
    yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


@router.post("/chat/completions", response_model=None)
def post_v1_chat_completion(
    request: ChatCompletionRequest,
    llm_client: LLMClient = Depends(get_llm_client),
) -> Any:
    if request.stream and isinstance(llm_client, LMStudioChatClient):
        with Session(get_engine()) as session:
            model = _resolve_selectable_model(session, request.model)
        question, context = _build_prompt(request.messages)

        retrieval_preview: dict[str, Any] | None = None
        if request.rag_collection_id:
            with Session(get_engine()) as session:
                try:
                    retrieval_preview = preview_collection_retrieval(
                        session,
                        collection_id=request.rag_collection_id,
                        query=question,
                        top_k=request.top_k,
                    )
                except KeyError as exc:
                    raise HTTPException(
                        status_code=404, detail="RAG collection not found"
                    ) from exc
            rag_context = (
                "\n\n".join(
                    f"[{item['filename']}]\n{item['excerpt']}"
                    for item in retrieval_preview.get("results", [])
                )
                or "No matching RAG collection context found."
            )
            context = (
                f"{context}\n\n"
                "Use the following platform RAG collection evidence when it is relevant. "
                "If it is insufficient, say so.\n\n"
                f"{rag_context}"
            )

        serving_model_name = model.get("serving_model_name")
        if not serving_model_name:
            raise HTTPException(
                status_code=409,
                detail=(
                    "selected model has no serving target; only runtime-ready/selectable "
                    "models can be used through the OpenAI-compatible shim"
                ),
            )

        completion_id = f"chatcmpl-{uuid.uuid4().hex}"
        created = int(time.time())
        exposed_model_id = _exposed_model_id(model) if model.get("id") else str(
            serving_model_name
        )
        platform_meta = {
            "registry_model_id": model.get("id"),
            "serving_model_name": serving_model_name,
            "source_type": model.get("source_type"),
            "readiness": model.get("readiness"),
            "rag_collection_id": request.rag_collection_id,
            "retrieval_preview": retrieval_preview,
            "notes": [
                "Stream chunks are proxied directly from LM Studio with id+model rewritten to the platform identifiers.",
                "RAG-collection grounding is opt-in via rag_collection_id.",
            ],
        }
        return StreamingResponse(
            _stream_via_lmstudio(
                llm_client=llm_client,
                question=question,
                context=context,
                serving_model_name=str(serving_model_name),
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                completion_id=completion_id,
                exposed_model_id=exposed_model_id,
                created=created,
                platform_meta=platform_meta,
            ),
            media_type="text/event-stream",
        )

    response, completion_id, exposed_model_id, created = _run_chat_completion(
        request, llm_client
    )
    if request.stream:
        # Fallback for non-LM-Studio clients (test fakes etc.): buffer + wrap.
        return StreamingResponse(
            _stream_chat_completion(response, completion_id, exposed_model_id, created),
            media_type="text/event-stream",
        )
    return response
