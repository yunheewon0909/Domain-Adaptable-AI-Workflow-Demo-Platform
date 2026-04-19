from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

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


class OllamaChatClient:
    def __init__(
        self,
        *,
        base_url: str,
        default_model: str,
        fallback_model: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._fallback_model = fallback_model
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
        last_error: Exception | None = None
        for candidate_model, used_fallback in self._model_candidates(model):
            try:
                content = self._chat_completion(
                    model=candidate_model,
                    question=question,
                    context=context,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if used_fallback:
                    raise LLMClientError(str(exc)) from exc
                continue

            return ChatResult(
                answer=content, model=candidate_model, used_fallback=used_fallback
            )

        if last_error is not None:
            raise LLMClientError(str(last_error)) from last_error
        raise LLMClientError("No model candidates configured")

    def _model_candidates(
        self, requested_model: str | None = None
    ) -> list[tuple[str, bool]]:
        if requested_model and requested_model.strip():
            return [(requested_model.strip(), False)]
        candidates: list[tuple[str, bool]] = [(self._default_model, False)]
        if self._fallback_model and self._fallback_model != self._default_model:
            candidates.append((self._fallback_model, True))
        return candidates

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
                            "Answer using only the provided context when possible. "
                            "If context is insufficient, say so briefly."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Context:\n{context}\n\nQuestion: {question}",
                    },
                ],
                "temperature": temperature,
                **({"max_tokens": max_tokens} if max_tokens is not None else {}),
            },
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()

        payload = response.json()
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("Invalid chat completion payload: missing choices")

        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ValueError(
                "Invalid chat completion payload: missing assistant content"
            )

        return content.strip()
