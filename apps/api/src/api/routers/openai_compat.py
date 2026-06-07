"""OpenAI-compatible shim (`/v1/*`) — what Open WebUI points at.

Backed by the configured runtime adapter (Ollama by default). Lists the
runtime's models, proxies chat completions (buffered or streamed), and supports
optional RAG grounding via the custom ``rag_collection_id`` body field. There is
no model registry / readiness gating any more (ADR 0008).
"""

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
from api.llm import LLMClient, LLMClientError
from api.services.rag.collections import preview_collection_retrieval
from api.services.runtime import get_chat_runtime

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


def _supports_streaming(llm_client: object) -> bool:
    return callable(getattr(llm_client, "stream_chat_messages", None))


def _runtime_model_ids() -> list[str]:
    try:
        return get_chat_runtime().list_model_ids()
    except Exception:
        return []


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
    question = (messages[last_user_idx].content or "").strip()
    if not question:
        raise HTTPException(
            status_code=400, detail="last user message must have non-empty content"
        )

    context_parts: list[str] = []
    for idx, message in enumerate(messages):
        if idx == last_user_idx:
            continue
        content = (message.content or "").strip()
        if content:
            context_parts.append(f"[{message.role}]\n{content}")
    context = "\n\n".join(context_parts) or "No prior context provided."
    return question, context


def _apply_rag_to_context(
    *, rag_collection_id: str, question: str, top_k: int, context: str
) -> tuple[str, dict[str, Any]]:
    with Session(get_engine()) as session:
        try:
            retrieval_preview = preview_collection_retrieval(
                session,
                collection_id=rag_collection_id,
                query=question,
                top_k=top_k,
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
    new_context = (
        f"{context}\n\n"
        "Use the following platform RAG collection evidence when it is relevant. "
        "If it is insufficient, say so.\n\n"
        f"{rag_context}"
    )
    return new_context, retrieval_preview


def _build_messages(*, question: str, context: str) -> list[dict[str, Any]]:
    return [
        {
            "role": "system",
            "content": (
                "Answer the user's question concisely. If the Context block "
                "contains relevant evidence, ground your answer in it; "
                "otherwise rely on your own knowledge."
            ),
        },
        {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
    ]


@router.get("/models")
def list_v1_models() -> dict[str, Any]:
    now = int(time.time())
    return {
        "object": "list",
        "data": [
            {"id": model_id, "object": "model", "created": now, "owned_by": OWNED_BY}
            for model_id in _runtime_model_ids()
        ],
    }


def _platform_meta(
    request: ChatCompletionRequest,
    retrieval_preview: dict[str, Any] | None,
    *,
    streamed: bool,
) -> dict[str, Any]:
    return {
        "model": request.model,
        "rag_collection_id": request.rag_collection_id,
        "retrieval_preview": retrieval_preview,
        "notes": [
            "Token counts are placeholders; the runtime shim does not report usage.",
            "RAG-collection grounding is opt-in via rag_collection_id.",
        ]
        + (
            ["Stream chunks are proxied from the runtime with id+model rewritten."]
            if streamed
            else []
        ),
    }


def _run_chat_completion(
    request: ChatCompletionRequest, llm_client: LLMClient
) -> tuple[dict[str, Any], str, str, int]:
    question, context = _build_prompt(request.messages)
    retrieval_preview: dict[str, Any] | None = None
    if request.rag_collection_id:
        context, retrieval_preview = _apply_rag_to_context(
            rag_collection_id=request.rag_collection_id,
            question=question,
            top_k=request.top_k,
            context=context,
        )

    try:
        result = llm_client.generate_answer(
            question=question,
            context=context,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
    except LLMClientError as exc:
        raise HTTPException(status_code=502, detail=f"LLM request failed: {exc}") from exc

    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    response = {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": request.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": result.answer},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "x_domain_platform": _platform_meta(request, retrieval_preview, streamed=False),
    }
    return response, completion_id, request.model, created


def _stream_via_runtime(
    *,
    llm_client: Any,
    question: str,
    context: str,
    model: str,
    temperature: float,
    max_tokens: int | None,
    completion_id: str,
    created: int,
    platform_meta: dict[str, Any],
) -> Iterator[str]:
    try:
        upstream = llm_client.stream_chat_messages(
            messages=_build_messages(question=question, context=context),
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        for chunk in upstream:
            chunk = dict(chunk)
            chunk["id"] = completion_id
            chunk["model"] = model
            chunk["created"] = created
            chunk.pop("system_fingerprint", None)
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
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": f"\n[stream error: {exc}]"},
                    "finish_reason": "stop",
                }
            ],
        }
        yield f"data: {json.dumps(error_chunk, ensure_ascii=False)}\n\n"

    # The upstream's own terminal chunk already carries finish_reason="stop";
    # this trailing chunk exists only to attach platform metadata, so it must
    # NOT emit a second non-null finish_reason (the OpenAI streaming contract
    # allows exactly one terminal chunk per choice).
    final_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": None}],
        "x_domain_platform": platform_meta,
    }
    yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


def _stream_buffered(
    response: dict[str, Any], completion_id: str, model: str, created: int
) -> Iterator[str]:
    content = response["choices"][0]["message"]["content"] or ""
    first = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
    }
    yield f"data: {json.dumps(first, ensure_ascii=False)}\n\n"
    if content:
        chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {"index": 0, "delta": {"content": content}, "finish_reason": None}
            ],
        }
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
    final = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        "x_domain_platform": response["x_domain_platform"],
    }
    yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


@router.post("/chat/completions", response_model=None)
def post_v1_chat_completion(
    request: ChatCompletionRequest,
    llm_client: LLMClient = Depends(get_llm_client),
) -> Any:
    if request.stream and _supports_streaming(llm_client):
        question, context = _build_prompt(request.messages)
        retrieval_preview: dict[str, Any] | None = None
        if request.rag_collection_id:
            context, retrieval_preview = _apply_rag_to_context(
                rag_collection_id=request.rag_collection_id,
                question=question,
                top_k=request.top_k,
                context=context,
            )
        completion_id = f"chatcmpl-{uuid.uuid4().hex}"
        created = int(time.time())
        return StreamingResponse(
            _stream_via_runtime(
                llm_client=llm_client,
                question=question,
                context=context,
                model=request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                completion_id=completion_id,
                created=created,
                platform_meta=_platform_meta(
                    request, retrieval_preview, streamed=True
                ),
            ),
            media_type="text/event-stream",
        )

    response, completion_id, model, created = _run_chat_completion(request, llm_client)
    if request.stream:
        return StreamingResponse(
            _stream_buffered(response, completion_id, model, created),
            media_type="text/event-stream",
        )
    return response
