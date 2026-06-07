from collections.abc import Iterator

from sqlalchemy.orm import Session

from api.db import get_engine
from api.llm import LLMClient
from api.services.rag.embedding_client import EmbeddingClient
from api.services.runtime import get_chat_runtime, get_embedding_runtime


def get_db_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def get_llm_client() -> LLMClient:
    # Provider-agnostic: Ollama by default, any OpenAI-compatible runtime via
    # config. The returned runtime satisfies the LLMClient protocol.
    return get_chat_runtime()


def get_embedding_client() -> EmbeddingClient:
    return get_embedding_runtime()
