from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from api.dependencies import get_llm_client
from api.llm import ChatResult
from api.main import app
from api.routers import openai_compat


@pytest.fixture(autouse=True)
def _fake_runtime_models(monkeypatch: pytest.MonkeyPatch) -> None:
    """The /v1/models list comes from the runtime; fake it so tests are offline."""
    monkeypatch.setattr(
        openai_compat, "_runtime_model_ids", lambda: ["llama3.2", "nomic-embed-text"]
    )


class _RecordingLLM:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate_answer(
        self, *, question, context, model=None, temperature=0, max_tokens=None
    ) -> ChatResult:
        self.calls.append(
            {"question": question, "context": context, "model": model}
        )
        return ChatResult(answer="an answer", model=model or "llama3.2", used_fallback=False)


def _override(client_obj) -> Iterator[None]:
    app.dependency_overrides[get_llm_client] = lambda: client_obj
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_llm_client, None)


def test_v1_models_lists_runtime_models(client: TestClient) -> None:
    data = client.get("/v1/models").json()
    assert data["object"] == "list"
    ids = [m["id"] for m in data["data"]]
    assert ids == ["llama3.2", "nomic-embed-text"]
    assert all(m["owned_by"] == openai_compat.OWNED_BY for m in data["data"])


def test_chat_completion_non_streaming(client: TestClient) -> None:
    recording = _RecordingLLM()
    app.dependency_overrides[get_llm_client] = lambda: recording
    try:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "llama3.2",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
    finally:
        app.dependency_overrides.pop(get_llm_client, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["model"] == "llama3.2"
    assert body["choices"][0]["message"]["content"] == "an answer"
    assert recording.calls and recording.calls[0]["question"] == "hello"


def test_chat_completion_streams_via_runtime(client: TestClient) -> None:
    streamed = [
        {
            "id": "raw-1",
            "object": "chat.completion.chunk",
            "model": "ollama-raw",
            "system_fingerprint": "leak",
            "choices": [
                {"index": 0, "delta": {"content": "Hello "}, "finish_reason": None}
            ],
        },
        {
            "id": "raw-1",
            "object": "chat.completion.chunk",
            "model": "ollama-raw",
            "choices": [
                {"index": 0, "delta": {"content": "world"}, "finish_reason": "stop"}
            ],
        },
    ]

    class _StreamingLLM:
        def generate_answer(self, **kwargs) -> ChatResult:  # pragma: no cover
            return ChatResult(answer="", model="x", used_fallback=False)

        def stream_chat_messages(self, *, messages, model=None, temperature=0, max_tokens=None):
            self.received = messages
            yield from streamed

    fake = _StreamingLLM()
    app.dependency_overrides[get_llm_client] = lambda: fake
    try:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "llama3.2",
                "messages": [{"role": "user", "content": "say hi"}],
                "stream": True,
            },
        )
    finally:
        app.dependency_overrides.pop(get_llm_client, None)

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    text = resp.text
    # id+model rewritten to the platform-exposed model; upstream id gone.
    assert "llama3.2" in text
    assert "raw-1" not in text
    assert "ollama-raw" not in text
    # system_fingerprint stripped; content survives; sentinel appended.
    assert "system_fingerprint" not in text
    assert "Hello " in text and "world" in text
    assert "data: [DONE]" in text
    assert [m["role"] for m in fake.received] == ["system", "user"]


def test_chat_completion_reasoning_mirrored_to_content(client: TestClient) -> None:
    streamed = [
        {
            "id": "r",
            "object": "chat.completion.chunk",
            "model": "raw",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "reasoning_content": "Thinking"},
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": "r",
            "object": "chat.completion.chunk",
            "model": "raw",
            "choices": [
                {"index": 0, "delta": {"content": "Final."}, "finish_reason": "stop"}
            ],
        },
    ]

    class _ThinkingLLM:
        def generate_answer(self, **kwargs) -> ChatResult:  # pragma: no cover
            return ChatResult(answer="", model="x", used_fallback=False)

        def stream_chat_messages(self, **kwargs):
            yield from streamed

    app.dependency_overrides[get_llm_client] = lambda: _ThinkingLLM()
    try:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "llama3.2",
                "messages": [{"role": "user", "content": "think"}],
                "stream": True,
            },
        )
    finally:
        app.dependency_overrides.pop(get_llm_client, None)

    text = resp.text
    # reasoning tokens mirrored into content for generic OpenAI clients.
    assert "Thinking" in text
    assert "Final." in text
