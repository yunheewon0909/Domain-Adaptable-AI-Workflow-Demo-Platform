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
            ollama_model_name="artifact::ft-job-test",
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


def test_admin_route_renders_console_with_internal_framing(client: TestClient) -> None:
    response = client.get("/admin")

    assert response.status_code == 200
    text = response.text
    assert "Internal admin console" in text
    assert "Workflow reviewer" in text
    assert "PLC testing MVP" in text
    assert "Fine-tuning" in text
    assert "Models" in text
    assert "RAG" in text


def test_admin_assets_are_served_alongside_demo_assets(client: TestClient) -> None:
    demo_assets = client.get("/demo/assets/app.js")
    admin_assets = client.get("/admin/assets/app.js")

    assert demo_assets.status_code == 200
    assert admin_assets.status_code == 200
    assert demo_assets.text == admin_assets.text


def test_legacy_demo_route_still_works(client: TestClient) -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    assert "Workflow reviewer" in response.text
