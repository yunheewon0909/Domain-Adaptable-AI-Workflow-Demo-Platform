from collections.abc import Iterator

from sqlalchemy.orm import Session

from api.config import get_settings
from api.db import get_engine
from api.llm import LLMClient, OllamaChatClient
from api.services.rag.embedding_client import EmbeddingClient, OllamaEmbeddingClient


def get_db_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def get_llm_client() -> LLMClient:
    settings = get_settings()
    return OllamaChatClient(
        base_url=settings.ollama_base_url,
        default_model=settings.ollama_model,
        fallback_model=settings.ollama_fallback_model,
        timeout_seconds=settings.ollama_timeout_seconds,
    )


def get_embedding_client() -> EmbeddingClient:
    settings = get_settings()
    return OllamaEmbeddingClient(
        base_url=settings.ollama_embed_base_url,
        model=settings.ollama_embed_model,
        timeout_seconds=settings.ollama_timeout_seconds,
    )
