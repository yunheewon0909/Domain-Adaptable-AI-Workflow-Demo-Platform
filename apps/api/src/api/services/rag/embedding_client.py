from __future__ import annotations

from typing import Protocol


class EmbeddingClientError(RuntimeError):
    pass


class EmbeddingClient(Protocol):
    """Embedding contract satisfied by the runtime adapters.

    The concrete implementations live in ``api.services.runtime``.
    """

    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...
