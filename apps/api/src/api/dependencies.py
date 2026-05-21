from collections.abc import Iterator

from sqlalchemy.orm import Session

from api.config import get_settings
from api.db import get_engine
from api.llm import LLMClient, LMStudioChatClient, OllamaChatClient
from api.services.rag.embedding_client import EmbeddingClient, LMStudioEmbeddingClient, OllamaEmbeddingClient


def get_db_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def get_llm_client() -> LLMClient:
    settings = get_settings()
    if settings.lmstudio_chat_model:
        return LMStudioChatClient(
            base_url=settings.lmstudio_base_url,
            default_model=settings.lmstudio_chat_model,
            timeout_seconds=settings.lmstudio_timeout_seconds,
        )
    return OllamaChatClient(
        base_url=settings.ollama_base_url,
        default_model=settings.ollama_model,
        fallback_model=settings.ollama_fallback_model,
        timeout_seconds=settings.ollama_timeout_seconds,
    )


def get_embedding_client() -> EmbeddingClient:
    settings = get_settings()
    if settings.lmstudio_embed_model:
        return LMStudioEmbeddingClient(
            base_url=settings.lmstudio_base_url,
            model=settings.lmstudio_embed_model,
            timeout_seconds=settings.lmstudio_timeout_seconds,
        )
    return OllamaEmbeddingClient(
        base_url=settings.ollama_embed_base_url,
        model=settings.ollama_embed_model,
        timeout_seconds=settings.ollama_timeout_seconds,
    )
