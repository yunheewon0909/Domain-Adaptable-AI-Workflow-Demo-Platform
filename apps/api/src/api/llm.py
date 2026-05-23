from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
import json
from typing import Any, Protocol

import httpx


class LLMClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChatResult:
    answer: str
    model: str
    used_fallback: bool


class LLMClient(Protocol):
    def generate_answer(
        self,
        *,
        question: str,
        context: str,
        model: str | None = None,
        temperature: float = 0,
        max_tokens: int | None = None,
    ) -> ChatResult: ...


class LMStudioChatClient:
    """LM Studio OpenAI-compatible chat client.

    LM Studio exposes /v1/chat/completions in OpenAI format but loads one model
    at a time (no fallback chain, no model switching in-flight).
    """

    def __init__(
        self,
        *,
        base_url: str,
        default_model: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._timeout_seconds = timeout_seconds

    def generate_answer(
        self,
        *,
        question: str,
        context: str,
        model: str | None = None,
        temperature: float = 0,
        max_tokens: int | None = None,
    ) -> ChatResult:
        try:
            content = self._chat_completion(
                model=model or self._default_model,
                question=question,
                context=context,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMClientError(str(exc)) from exc

        return ChatResult(
            answer=content, model=model or self._default_model, used_fallback=False
        )

    def _chat_completion(
        self,
        *,
        model: str,
        question: str,
        context: str,
        temperature: float,
        max_tokens: int | None,
    ) -> str:
        response = httpx.post(
            f"{self._base_url}/chat/completions",
            json={
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Answer the user's question concisely. If the "
                            "Context block contains relevant evidence, ground "
                            "your answer in it; otherwise rely on your own "
                            "knowledge."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Context:\n{context}\n\nQuestion: {question}",
                    },
                ],
                "temperature": temperature,
                # Suppress Qwen3 / DeepSeek-R1 thinking pass so demo answers
                # stay concise instead of dumping reasoning_content into the
                # chat panel. Non-thinking models silently ignore this kwarg.
                "chat_template_kwargs": {"enable_thinking": False},
                **({"max_tokens": max_tokens} if max_tokens is not None else {}),
            },
            timeout=httpx.Timeout(
                connect=5.0,
                read=self._timeout_seconds,
                write=self._timeout_seconds,
                pool=5.0,
            ),
        )
        response.raise_for_status()

        payload = response.json()
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("Invalid chat completion payload: missing choices")

        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            raise ValueError(
                "Invalid chat completion payload: missing assistant message"
            )
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            # Qwen3 / DeepSeek-R1 style reasoning models put output in
            # `reasoning_content` and leave `content` empty when only the
            # thinking pass ran (e.g. truncated by max_tokens).
            reasoning = message.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning.strip():
                return reasoning.strip()
            raise ValueError(
                "Invalid chat completion payload: missing assistant content"
            )

        return content.strip()

    def stream_chat_messages(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0,
        max_tokens: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Stream raw chat-completion chunks from LM Studio.

        Yields decoded `data: ...` events as dicts. The terminal `[DONE]`
        sentinel is consumed and not yielded. Callers can rewrite the `id`
        and `model` fields before re-encoding the chunks for downstream
        clients.
        """
        body: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        timeout = httpx.Timeout(
            connect=5.0,
            read=self._timeout_seconds,
            write=self._timeout_seconds,
            pool=5.0,
        )
        try:
            with httpx.Client(timeout=timeout) as client:
                with client.stream(
                    "POST",
                    f"{self._base_url}/chat/completions",
                    json=body,
                ) as response:
                    response.raise_for_status()
                    for raw_line in response.iter_lines():
                        if not raw_line:
                            continue
                        line = raw_line.strip()
                        if not line.startswith("data:"):
                            continue
                        payload_text = line[len("data:") :].strip()
                        if payload_text == "[DONE]":
                            return
                        try:
                            chunk = json.loads(payload_text)
                        except json.JSONDecodeError as exc:
                            raise LLMClientError(
                                f"LM Studio stream returned invalid JSON: {exc}"
                            ) from exc
                        if isinstance(chunk, dict):
                            yield chunk
        except httpx.HTTPError as exc:
            raise LLMClientError(str(exc)) from exc
