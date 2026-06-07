"""Integration tests covering end-to-end happy paths for key API flows."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.dependencies import get_llm_client
from api.routers import models as models_router
from api.routers import openai_compat


class _FakeLLMClient:
    def generate_answer(self, *, question, context, model=None, temperature=0, max_tokens=None):
        class _R:
            answer = "fake answer"
            used_fallback = False

            def __init__(self, m):
                self.model = m or "fake"

        return _R(model)


@pytest.fixture(autouse=True)
def _fake_runtime_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(openai_compat, "_runtime_model_ids", lambda: ["llama3.2"])
    monkeypatch.setattr(models_router, "_runtime_model_ids", lambda: ["llama3.2"])


# ---------------------------------------------------------------------------
# RAG collection upload
# ---------------------------------------------------------------------------


def test_rag_collection_create_and_upload(client: TestClient) -> None:
    coll_resp = client.post(
        "/rag-collections",
        json={"name": "Test KB", "description": "desc"},
    )
    assert coll_resp.status_code == 201, coll_resp.text
    coll_id = coll_resp.json()["id"]

    list_resp = client.get("/rag-collections")
    assert list_resp.status_code == 200
    ids = [c["id"] for c in list_resp.json()]
    assert coll_id in ids

    doc_resp = client.post(
        f"/rag-collections/{coll_id}/documents",
        files={"file": ("test.txt", b"Hello world content", "text/plain")},
    )
    assert doc_resp.status_code == 201, doc_resp.text
    doc_body = doc_resp.json()
    assert doc_body["filename"] == "test.txt"
    assert doc_body["collection_id"] == coll_id

    coll_get = client.get(f"/rag-collections/{coll_id}")
    assert coll_get.status_code == 200
    assert coll_get.json()["document_count"] == 1


def test_rag_collection_not_found(client: TestClient) -> None:
    resp = client.get("/rag-collections/does-not-exist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Model listing + inference (runtime-backed)
# ---------------------------------------------------------------------------


def test_models_endpoint_lists_runtime_models(client: TestClient) -> None:
    resp = client.get("/models")
    assert resp.status_code == 200
    ids = [m["id"] for m in resp.json()["data"]]
    assert ids == ["llama3.2"]


def test_v1_models_lists_runtime_models(client: TestClient) -> None:
    resp = client.get("/v1/models")
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "list"
    assert [m["id"] for m in body["data"]] == ["llama3.2"]


def test_v1_chat_completion_with_fake_llm(client: TestClient) -> None:
    fake = _FakeLLMClient()
    client.app.dependency_overrides[get_llm_client] = lambda: fake  # type: ignore[attr-defined]
    try:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "llama3.2",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["choices"][0]["message"]["content"] == "fake answer"
    finally:
        client.app.dependency_overrides.pop(get_llm_client, None)  # type: ignore[attr-defined]


def test_inference_run_with_fake_llm(client: TestClient) -> None:
    fake = _FakeLLMClient()
    client.app.dependency_overrides[get_llm_client] = lambda: fake  # type: ignore[attr-defined]
    try:
        resp = client.post(
            "/inference/run",
            json={"prompt": "Hello", "model": "llama3.2"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["answer"] == "fake answer"
    finally:
        client.app.dependency_overrides.pop(get_llm_client, None)  # type: ignore[attr-defined]
