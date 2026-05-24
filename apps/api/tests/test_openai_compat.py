from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.db import get_engine
from api.dependencies import get_llm_client
from api.main import app
from api.models import ModelRegistryRecord
from api.services.rag.collections import add_collection_document, create_collection


class _FakeChatResult:
    def __init__(self, *, answer: str, model: str, used_fallback: bool = False) -> None:
        self.answer = answer
        self.model = model
        self.used_fallback = used_fallback


class _RecordingLLMClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate_answer(
        self,
        *,
        question: str,
        context: str,
        model: str | None = None,
        temperature: float = 0,
        max_tokens: int | None = None,
    ) -> _FakeChatResult:
        self.calls.append(
            {
                "question": question,
                "context": context,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return _FakeChatResult(
            answer=f"answer::{question}::{model}",
            model=model or "default-model",
        )


@pytest.fixture
def recording_llm() -> _RecordingLLMClient:
    return _RecordingLLMClient()


@pytest.fixture
def client_with_llm(
    client: TestClient, recording_llm: _RecordingLLMClient
) -> Iterator[TestClient]:
    app.dependency_overrides[get_llm_client] = lambda: recording_llm
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_llm_client, None)


def _add_artifact_only_fine_tuned_model() -> str:
    with Session(get_engine()) as session:
        record = ModelRegistryRecord(
            id="model-ft-artifact-only",
            display_name="Artifact-only fine-tuned",
            source_type="fine_tuned",
            base_model_name="qwen3.5:4b",
            serving_model_name="artifact::ft-job-test",
            published_model_name=None,
            status="artifact_ready",
            publish_status="publish_ready",
            tags_json=["fine_tuned", "test"],
            description="Artifact-only model used for OpenAI shim gating tests.",
        )
        session.add(record)
        session.commit()
        return record.id


def test_v1_models_exposes_only_selectable_rows(client: TestClient) -> None:
    response = client.get("/v1/models")

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert isinstance(body["data"], list)
    assert body["data"], "expected at least one default selectable model"
    for entry in body["data"]:
        assert entry["object"] == "model"
        assert entry["owned_by"] == "domain-adaptable-ai-platform"
        assert entry["id"]
        assert "platform model" in entry["id"]
        assert entry["registry_id"]
        assert entry["serving_model_name"]
        assert entry["readiness"]["selectable"] is True


def test_v1_models_excludes_artifact_only_rows(client: TestClient) -> None:
    artifact_only_id = _add_artifact_only_fine_tuned_model()

    response = client.get("/v1/models")

    assert response.status_code == 200
    exposed_ids = {entry["id"] for entry in response.json()["data"]}
    assert artifact_only_id not in exposed_ids


def test_v1_chat_completions_returns_openai_shape(
    client_with_llm: TestClient, recording_llm: _RecordingLLMClient
) -> None:
    listing = client_with_llm.get("/v1/models").json()["data"]
    assert listing, "default model fixture missing"
    selected = listing[0]

    response = client_with_llm.post(
        "/v1/chat/completions",
        json={
            "model": selected["id"],
            "messages": [
                {"role": "system", "content": "Reply briefly."},
                {"role": "user", "content": "ping"},
            ],
            "temperature": 0,
            "max_tokens": 16,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["model"] == selected["id"]
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert body["choices"][0]["message"]["content"]
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["usage"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    platform_meta = body["x_domain_platform"]
    assert platform_meta["registry_model_id"] == selected["registry_id"]
    assert platform_meta["serving_model_name"] == selected["serving_model_name"]
    assert platform_meta["readiness"]["selectable"] is True

    assert recording_llm.calls, "LLM client should have been invoked"
    call = recording_llm.calls[-1]
    assert call["question"] == "ping"
    assert "[system]" in str(call["context"])
    assert call["model"] == selected["serving_model_name"]
    assert call["temperature"] == 0
    assert call["max_tokens"] == 16



def test_v1_chat_completions_accepts_registry_id_for_backward_compatibility(
    client_with_llm: TestClient,
) -> None:
    selected = client_with_llm.get("/v1/models").json()["data"][0]

    response = client_with_llm.post(
        "/v1/chat/completions",
        json={
            "model": selected["registry_id"],
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["model"] == selected["id"]



def test_v1_chat_completions_can_ground_with_rag_collection(
    client_with_llm: TestClient, recording_llm: _RecordingLLMClient
) -> None:
    selected = client_with_llm.get("/v1/models").json()["data"][0]
    with Session(get_engine()) as session:
        collection = create_collection(
            session,
            name="OpenAI shim grounding test",
            description=None,
            embedding_model=None,
            chunking_policy_json={},
        )
        add_collection_document(
            session,
            collection_id=collection["id"],
            filename="maintenance-note.txt",
            mime_type="text/plain",
            source_type="test",
            content=b"Maintenance automation evidence says inspect the servo alarm.",
        )

    response = client_with_llm.post(
        "/v1/chat/completions",
        json={
            "model": selected["id"],
            "messages": [{"role": "user", "content": "maintenance automation"}],
            "rag_collection_id": collection["id"],
            "top_k": 2,
        },
    )

    assert response.status_code == 200
    body = response.json()
    platform_meta = body["x_domain_platform"]
    assert platform_meta["rag_collection_id"] == collection["id"]
    assert platform_meta["retrieval_preview"]["results"]
    assert "servo alarm" in str(recording_llm.calls[-1]["context"])

def test_v1_chat_completions_rejects_missing_rag_collection(
    client_with_llm: TestClient,
) -> None:
    selected = client_with_llm.get("/v1/models").json()["data"][0]

    response = client_with_llm.post(
        "/v1/chat/completions",
        json={
            "model": selected["id"],
            "messages": [{"role": "user", "content": "hello"}],
            "rag_collection_id": "missing-collection",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "RAG collection not found"

def test_v1_chat_completions_accepts_serving_model_name(
    client_with_llm: TestClient,
) -> None:
    listing = client_with_llm.get("/v1/models").json()["data"]
    serving_name = listing[0]["serving_model_name"]

    response = client_with_llm.post(
        "/v1/chat/completions",
        json={
            "model": serving_name,
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["x_domain_platform"]["serving_model_name"] == serving_name


def test_v1_chat_completions_rejects_artifact_only_model(
    client_with_llm: TestClient,
) -> None:
    artifact_only_id = _add_artifact_only_fine_tuned_model()

    response = client_with_llm.post(
        "/v1/chat/completions",
        json={
            "model": artifact_only_id,
            "messages": [{"role": "user", "content": "ping"}],
        },
    )

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert "artifact" in detail.lower() or "selectable" in detail.lower() or "serving" in detail.lower()


def test_v1_chat_completions_rejects_unknown_model(
    client_with_llm: TestClient,
) -> None:
    response = client_with_llm.post(
        "/v1/chat/completions",
        json={
            "model": "does-not-exist",
            "messages": [{"role": "user", "content": "ping"}],
        },
    )

    assert response.status_code == 404


def test_v1_chat_completions_supports_streaming_sse(
    client_with_llm: TestClient,
) -> None:
    listing = client_with_llm.get("/v1/models").json()["data"]
    response = client_with_llm.post(
        "/v1/chat/completions",
        json={
            "model": listing[0]["id"],
            "messages": [{"role": "user", "content": "ping"}],
            "stream": True,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    text = response.text
    assert "data: " in text
    assert "chat.completion.chunk" in text
    assert "answer::ping" in text
    assert "data: [DONE]" in text


def test_v1_chat_completions_streams_real_lmstudio_chunks(
    client: TestClient,
) -> None:
    """When the LLM client is a real LMStudioChatClient, /v1/chat/completions
    proxies LM Studio's SSE chunks directly (id+model rewritten)."""
    from api.llm import LMStudioChatClient
    from api.main import app

    listing = client.get("/v1/models").json()["data"]
    selected = listing[0]

    streamed_chunks = [
        {
            "id": "lmstudio-1",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": selected["serving_model_name"],
            "choices": [
                {"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}
            ],
        },
        {
            "id": "lmstudio-1",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": selected["serving_model_name"],
            "choices": [
                {"index": 0, "delta": {"content": "Hello "}, "finish_reason": None}
            ],
        },
        {
            "id": "lmstudio-1",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": selected["serving_model_name"],
            "choices": [
                {"index": 0, "delta": {"content": "world"}, "finish_reason": "stop"}
            ],
        },
    ]

    class _FakeLMStudio(LMStudioChatClient):
        def __init__(self) -> None:
            super().__init__(
                base_url="http://127.0.0.1:1234/v1",
                default_model=selected["serving_model_name"],
            )
            self.received_messages: list[dict[str, object]] = []

        def stream_chat_messages(self, *, messages, model=None, temperature=0, max_tokens=None):
            self.received_messages = messages
            for chunk in streamed_chunks:
                yield chunk

    fake = _FakeLMStudio()
    from api.dependencies import get_llm_client
    app.dependency_overrides[get_llm_client] = lambda: fake

    try:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": selected["id"],
                "messages": [{"role": "user", "content": "say hi"}],
                "stream": True,
            },
        )
    finally:
        app.dependency_overrides.pop(get_llm_client, None)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    text = response.text

    # All three upstream chunks present
    assert text.count("chat.completion.chunk") >= 4  # 3 upstream + final platform chunk
    # id+model rewritten to the platform exposed values
    assert selected["id"] in text
    assert "lmstudio-1" not in text
    # Content survives the pass-through
    assert "Hello " in text
    assert "world" in text
    # Terminal sentinel + platform metadata appended
    assert "x_domain_platform" in text
    assert "data: [DONE]" in text
    # The system+user prompt envelope is delivered to LM Studio
    roles = [m["role"] for m in fake.received_messages]
    assert roles == ["system", "user"]


def test_v1_chat_completions_stream_mirrors_reasoning_content_to_content(
    client: TestClient,
) -> None:
    """Thinking-mode models (Qwen3 etc.) stream tokens in `reasoning_content`
    and leave `content` empty until the post-think summary. Generic OpenAI
    SSE clients only render `delta.content`, so the shim mirrors reasoning
    tokens into `content` while the reasoning pass is still running.
    """
    from api.llm import LMStudioChatClient
    from api.main import app

    listing = client.get("/v1/models").json()["data"]
    selected = listing[0]

    streamed_chunks = [
        {
            "id": "lmstudio-1",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": selected["serving_model_name"],
            "system_fingerprint": selected["serving_model_name"],
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "reasoning_content": "Thinking"},
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": "lmstudio-1",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": selected["serving_model_name"],
            "system_fingerprint": selected["serving_model_name"],
            "choices": [
                {
                    "index": 0,
                    "delta": {"reasoning_content": " harder"},
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": "lmstudio-1",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": selected["serving_model_name"],
            "system_fingerprint": selected["serving_model_name"],
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": "Final answer."},
                    "finish_reason": "stop",
                }
            ],
        },
    ]

    class _FakeLMStudio(LMStudioChatClient):
        def __init__(self) -> None:
            super().__init__(
                base_url="http://127.0.0.1:1234/v1",
                default_model=selected["serving_model_name"],
            )

        def stream_chat_messages(self, *, messages, model=None, temperature=0, max_tokens=None):
            for chunk in streamed_chunks:
                yield chunk

    from api.dependencies import get_llm_client

    app.dependency_overrides[get_llm_client] = lambda: _FakeLMStudio()
    try:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": selected["id"],
                "messages": [{"role": "user", "content": "think hard then answer"}],
                "stream": True,
            },
        )
    finally:
        app.dependency_overrides.pop(get_llm_client, None)

    assert response.status_code == 200
    text = response.text
    # system_fingerprint must NOT leak the upstream serving name past the shim
    assert "system_fingerprint" not in text
    # reasoning_content tokens are mirrored into content for generic clients
    assert "Thinking" in text
    assert "harder" in text
    # Real assistant content (post-think summary) also lands in content
    assert "Final answer." in text


def test_v1_chat_completions_requires_user_message(
    client_with_llm: TestClient,
) -> None:
    listing = client_with_llm.get("/v1/models").json()["data"]
    response = client_with_llm.post(
        "/v1/chat/completions",
        json={
            "model": listing[0]["id"],
            "messages": [
                {"role": "system", "content": "Reply briefly."},
                {"role": "assistant", "content": "nothing user said yet"},
            ],
        },
    )

    assert response.status_code == 400
    assert "user message" in response.json()["detail"].lower()


def test_legacy_demo_route_still_works(client: TestClient) -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    assert "Knowledge base" in response.text
