from __future__ import annotations

from typing import Protocol

import httpx


class EmbeddingClientError(RuntimeError):
    pass


class EmbeddingClient(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


class OllamaEmbeddingClient:
    def __init__(self, *, base_url: str, model: str, timeout_seconds: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        try:
            response = httpx.post(
                f"{self._base_url}/embeddings",
                json={"model": self._model, "input": texts},
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
                raise EmbeddingClientError("Invalid embeddings payload: missing embedding vector")
            vectors.append([float(value) for value in embedding])

        if len(vectors) != len(texts):
            raise EmbeddingClientError(
                f"Invalid embeddings payload: expected {len(texts)} vectors, got {len(vectors)}"
            )

        return vectors


class LMStudioEmbeddingClient:
    """LM Studio embedding client.

    LM Studio 0.2.19+ exposes /v1/embeddings in OpenAI-compatible format.
    Loads one embedding model at a time (e.g. mxbai-embed-large-mlx).
    """

    def __init__(self, *, base_url: str, model: str, timeout_seconds: float = 60.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        try:
            response = httpx.post(
                f"{self._base_url}/embeddings",
                json={"model": self._model, "input": texts},
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
