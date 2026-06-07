"""Runtime adapter: provider-agnostic chat + embedding access.

All LLM/embedding calls in the platform go through these protocols so the
serving runtime is a configuration choice, not a hardcoded vendor. The default
provider is Ollama (the bundled container); LM Studio and any other
OpenAI-compatible endpoint are available via ``LLM_RUNTIME_PROVIDER=openai_compat``.

See ADR 0009.
"""

from __future__ import annotations

from api.config import Settings, get_settings
from api.services.runtime.base import (
    ChatRuntime,
    EmbeddingRuntime,
    OpenAICompatRuntime,
)
from api.services.runtime.ollama import OllamaRuntime

__all__ = [
    "ChatRuntime",
    "EmbeddingRuntime",
    "OpenAICompatRuntime",
    "OllamaRuntime",
    "build_chat_runtime",
    "build_embedding_runtime",
    "get_chat_runtime",
    "get_embedding_runtime",
]


def _build(settings: Settings) -> OpenAICompatRuntime:
    """Construct the configured runtime (it implements both chat + embedding)."""
    provider = (settings.llm_runtime_provider or "ollama").strip().lower()
    if provider == "ollama":
        return OllamaRuntime(
            base_url=settings.llm_base_url,
            chat_model=settings.llm_chat_model,
            embed_model=settings.llm_embed_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    # "openai_compat" (and any LM-Studio / OpenAI-compatible endpoint).
    return OpenAICompatRuntime(
        base_url=settings.llm_base_url,
        chat_model=settings.llm_chat_model,
        embed_model=settings.llm_embed_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )


def build_chat_runtime(settings: Settings | None = None) -> ChatRuntime:
    return _build(settings or get_settings())


def build_embedding_runtime(settings: Settings | None = None) -> EmbeddingRuntime:
    return _build(settings or get_settings())


def get_chat_runtime() -> ChatRuntime:
    return build_chat_runtime()


def get_embedding_runtime() -> EmbeddingRuntime:
    return build_embedding_runtime()
