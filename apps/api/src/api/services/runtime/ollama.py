"""Ollama runtime adapter — the Docker-first default.

Ollama exposes an OpenAI-compatible surface under ``/v1`` (chat + embeddings) and
its own native endpoints under ``/api`` (e.g. ``/api/tags`` for the installed
model list). We reuse the OpenAI-compatible base for chat/embeddings and use the
native ``/api/tags`` for listing, which reflects what the Ollama daemon actually
has pulled.
"""

from __future__ import annotations

import httpx

from api.llm import LLMClientError
from api.services.runtime.base import OpenAICompatRuntime


class OllamaRuntime(OpenAICompatRuntime):
    def __init__(
        self,
        *,
        base_url: str,
        chat_model: str = "",
        embed_model: str = "",
        timeout_seconds: float = 60.0,
    ) -> None:
        # `base_url` is the Ollama root (e.g. http://ollama:11434). The OpenAI
        # dialect lives under /v1; keep the root for native /api calls.
        self._native_base = base_url.rstrip("/")
        super().__init__(
            base_url=f"{self._native_base}/v1",
            chat_model=chat_model,
            embed_model=embed_model,
            timeout_seconds=timeout_seconds,
        )

    @property
    def native_base_url(self) -> str:
        return self._native_base

    def list_model_ids(self) -> list[str]:
        """List pulled models via Ollama's native ``/api/tags``."""
        try:
            response = httpx.get(f"{self._native_base}/api/tags", timeout=5.0)
            response.raise_for_status()
            models = response.json().get("models", [])
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMClientError(str(exc)) from exc
        return [
            str(item.get("name"))
            for item in models
            if isinstance(item, dict) and item.get("name")
        ]
