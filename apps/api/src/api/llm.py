from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class LLMClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChatResult:
    answer: str
    model: str
    used_fallback: bool


class LLMClient(Protocol):
    """Minimal chat contract satisfied by the runtime adapters.

    The concrete implementations live in ``api.services.runtime``.
    """

    def generate_answer(
        self,
        *,
        question: str,
        context: str,
        model: str | None = None,
        temperature: float = 0,
        max_tokens: int | None = None,
    ) -> ChatResult: ...
