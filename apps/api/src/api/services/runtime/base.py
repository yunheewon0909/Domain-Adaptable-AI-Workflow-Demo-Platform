"""Runtime protocols + the OpenAI-compatible base implementation.

`OpenAICompatRuntime` speaks the OpenAI `/v1/*` dialect and therefore covers
Ollama's OpenAI-compatible surface, LM Studio, and any other OpenAI-compatible
server. `OllamaRuntime` (see ``ollama.py``) subclasses it to add Ollama's native
model listing.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, Protocol, runtime_checkable

import httpx

from api.llm import ChatResult, LLMClientError
from api.services.rag.embedding_client import EmbeddingClientError

# System prompt shared by chat paths (kept identical to the prior LM Studio
# client so behaviour — including the "own knowledge" fallback — is unchanged).
_SYSTEM_PROMPT = (
    "Answer the user's question concisely. If the Context block contains "
    "relevant evidence, ground your answer in it; otherwise rely on your own "
    "knowledge."
)


@runtime_checkable
class ChatRuntime(Protocol):
    def generate_answer(
        self,
        *,
        question: str,
        context: str,
        model: str | None = None,
        temperature: float = 0,
        max_tokens: int | None = None,
    ) -> ChatResult: ...

    def stream_chat_messages(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0,
        max_tokens: int | None = None,
    ) -> Iterator[dict[str, Any]]: ...

    def list_model_ids(self) -> list[str]: ...


@runtime_checkable
class EmbeddingRuntime(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


class OpenAICompatRuntime:
    """Chat + embedding runtime for any OpenAI-compatible endpoint.

    ``base_url`` is the OpenAI base (e.g. ``http://localhost:1234/v1`` for LM
    Studio, ``http://ollama:11434/v1`` for Ollama).
    """

    def __init__(
        self,
        *,
        base_url: str,
        chat_model: str = "",
        embed_model: str = "",
        timeout_seconds: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._chat_model = chat_model
        self._embed_model = embed_model
        self._timeout_seconds = timeout_seconds

    # --- introspection -------------------------------------------------
    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def default_chat_model(self) -> str:
        return self._chat_model

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=5.0,
            read=self._timeout_seconds,
            write=self._timeout_seconds,
            pool=5.0,
        )

    # --- chat ----------------------------------------------------------
    def generate_answer(
        self,
        *,
        question: str,
        context: str,
        model: str | None = None,
        temperature: float = 0,
        max_tokens: int | None = None,
    ) -> ChatResult:
        chosen = model or self._chat_model
        try:
            content = self._chat_completion(
                model=chosen,
                question=question,
                context=context,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMClientError(str(exc)) from exc
        return ChatResult(answer=content, model=chosen, used_fallback=False)

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
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"Context:\n{context}\n\nQuestion: {question}",
                    },
                ],
                "temperature": temperature,
                **({"max_tokens": max_tokens} if max_tokens is not None else {}),
            },
            timeout=self._timeout(),
        )
        response.raise_for_status()

        payload = response.json()
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("Invalid chat completion payload: missing choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            raise ValueError("Invalid chat completion payload: missing assistant message")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            reasoning = message.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning.strip():
                raise ValueError(
                    "Model ran out of tokens during its reasoning pass and did "
                    "not emit a final answer. Increase max_tokens (the current "
                    "budget was consumed entirely by the thinking phase)."
                )
            raise ValueError("Invalid chat completion payload: missing assistant content")
        return content.strip()

    def stream_chat_messages(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0,
        max_tokens: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        body: dict[str, Any] = {
            "model": model or self._chat_model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        try:
            with httpx.Client(timeout=self._timeout()) as client:
                with client.stream(
                    "POST", f"{self._base_url}/chat/completions", json=body
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
                                f"runtime stream returned invalid JSON: {exc}"
                            ) from exc
                        if isinstance(chunk, dict):
                            yield chunk
        except httpx.HTTPError as exc:
            raise LLMClientError(str(exc)) from exc

    # --- model listing -------------------------------------------------
    def list_model_ids(self) -> list[str]:
        """Return model ids served by the runtime (OpenAI `/v1/models`)."""
        try:
            response = httpx.get(f"{self._base_url}/models", timeout=5.0)
            response.raise_for_status()
            data = response.json().get("data", [])
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMClientError(str(exc)) from exc
        return [
            str(item.get("id"))
            for item in data
            if isinstance(item, dict) and item.get("id")
        ]

    # --- embeddings ----------------------------------------------------
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = httpx.post(
                f"{self._base_url}/embeddings",
                json={"model": self._embed_model, "input": texts},
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise EmbeddingClientError(str(exc)) from exc
        payload = response.json()
        data = payload.get("data")
        if not isinstance(data, list):
            raise EmbeddingClientError("Invalid embeddings payload: missing data")
        vectors: list[list[float]] = []
        for item in data:
            embedding = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(embedding, list) or not embedding:
                raise EmbeddingClientError(
                    "Invalid embeddings payload: missing embedding vector"
                )
            vectors.append([float(value) for value in embedding])
        if len(vectors) != len(texts):
            raise EmbeddingClientError(
                f"Invalid embeddings payload: expected {len(texts)} vectors, got {len(vectors)}"
            )
        return vectors
