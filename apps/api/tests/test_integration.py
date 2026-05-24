"""Integration tests covering end-to-end happy paths for key API flows."""
from __future__ import annotations

from fastapi.testclient import TestClient

from api.dependencies import get_llm_client


class _FakeLLMClient:
    def generate_answer(self, *, question, context, model=None, temperature=0, max_tokens=None):
        class _R:
            answer = "fake answer"
            used_fallback = False

            def __init__(self, m):
                self.model = m or "fake"

        return _R(model)


# ---------------------------------------------------------------------------
# Dataset create + list
# ---------------------------------------------------------------------------


def test_dataset_create_and_list(client: TestClient) -> None:
    resp = client.post(
        "/ft-datasets",
        json={"name": "My Dataset", "task_type": "instruction_sft", "schema_type": "json"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "My Dataset"
    assert body["task_type"] == "instruction_sft"
    dataset_id = body["id"]

    resp = client.get("/ft-datasets")
    assert resp.status_code == 200
    ids = [d["id"] for d in resp.json()]
    assert dataset_id in ids


def test_dataset_create_invalid_task_type(client: TestClient) -> None:
    resp = client.post(
        "/ft-datasets",
        json={"name": "Bad", "task_type": "nonexistent", "schema_type": "json"},
    )
    assert resp.status_code == 400


def test_dataset_get_not_found(client: TestClient) -> None:
    resp = client.get("/ft-datasets/does-not-exist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Training job lifecycle (queued → visible in list)
# ---------------------------------------------------------------------------


def test_training_job_lifecycle(client: TestClient, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRAINING_ARTIFACT_DIR", str(tmp_path / "artifacts"))

    # Create dataset + version + rows
    ds = client.post(
        "/ft-datasets",
        json={"name": "Train DS", "task_type": "instruction_sft", "schema_type": "json"},
    )
    assert ds.status_code == 201, ds.text
    ds_id = ds.json()["id"]

    version_resp = client.post(
        f"/ft-datasets/{ds_id}/versions",
        json={"version_label": "v1", "train_split_ratio": 0.8, "val_split_ratio": 0.1, "test_split_ratio": 0.1},
    )
    assert version_resp.status_code == 201, version_resp.text
    version_id = version_resp.json()["id"]

    rows_resp = client.post(
        f"/ft-dataset-versions/{version_id}/rows",
        json={
            "rows": [
                {"split": "train", "input_json": "What is AI?", "target_json": "Artificial Intelligence."},
                {"split": "val", "input_json": "What is ML?", "target_json": "Machine Learning."},
            ]
        },
    )
    assert rows_resp.status_code == 201, rows_resp.text

    # Validate + lock
    validate_resp = client.post(
        f"/ft-dataset-versions/{version_id}/status",
        json={"status": "validated"},
    )
    assert validate_resp.status_code == 200, validate_resp.text

    lock_resp = client.post(
        f"/ft-dataset-versions/{version_id}/status",
        json={"status": "locked"},
    )
    assert lock_resp.status_code == 200, lock_resp.text

    # Enqueue training job
    job_resp = client.post(
        "/ft-training-jobs",
        json={
            "dataset_version_id": version_id,
            "base_model_name": "qwen3.5:4b",
            "training_method": "sft_qlora",
        },
    )
    assert job_resp.status_code == 202, job_resp.text
    job_body = job_resp.json()
    assert job_body["status"] == "queued"
    job_id = job_body["id"]

    # Job appears in list
    list_resp = client.get("/ft-training-jobs")
    assert list_resp.status_code == 200
    ids = [j["id"] for j in list_resp.json()]
    assert job_id in ids

    # Get individual job
    get_resp = client.get(f"/ft-training-jobs/{job_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == job_id


# ---------------------------------------------------------------------------
# RAG collection upload
# ---------------------------------------------------------------------------


def test_rag_collection_create_and_upload(client: TestClient, tmp_path, monkeypatch) -> None:
    # Create collection
    coll_resp = client.post(
        "/rag-collections",
        json={"name": "Test KB", "description": "desc"},
    )
    assert coll_resp.status_code == 201, coll_resp.text
    coll_id = coll_resp.json()["id"]

    # List collections
    list_resp = client.get("/rag-collections")
    assert list_resp.status_code == 200
    ids = [c["id"] for c in list_resp.json()]
    assert coll_id in ids

    # Upload a document
    doc_resp = client.post(
        f"/rag-collections/{coll_id}/documents",
        files={"file": ("test.txt", b"Hello world content", "text/plain")},
    )
    assert doc_resp.status_code == 201, doc_resp.text
    doc_body = doc_resp.json()
    assert doc_body["filename"] == "test.txt"
    assert doc_body["collection_id"] == coll_id

    # Collection now has 1 document
    coll_get = client.get(f"/rag-collections/{coll_id}")
    assert coll_get.status_code == 200
    assert coll_get.json()["document_count"] == 1


def test_rag_collection_not_found(client: TestClient) -> None:
    resp = client.get("/rag-collections/does-not-exist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /v1/models endpoint
# ---------------------------------------------------------------------------


def test_v1_models_returns_selectable_models(client: TestClient) -> None:
    resp = client.get("/v1/models")
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "list"
    assert isinstance(body["data"], list)
    # Default model seeded by conftest env (LMSTUDIO_CHAT_MODEL=qwen3.5:4b) should be present
    ids = [m["id"] for m in body["data"]]
    assert any("default" in mid.lower() for mid in ids), f"Expected default model in: {ids}"


def test_v1_chat_completion_with_fake_llm(client: TestClient) -> None:
    fake = _FakeLLMClient()
    client.app.dependency_overrides[get_llm_client] = lambda: fake  # type: ignore[attr-defined]
    try:
        # Discover the actual exposed model id for the default seeded model
        models_resp = client.get("/v1/models")
        assert models_resp.status_code == 200
        data = models_resp.json()["data"]
        default_model = next(
            (m for m in data if "default" in m["id"].lower()),
            None,
        )
        assert default_model is not None, f"No default model found in: {[m['id'] for m in data]}"
        model_id = default_model["id"]

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": model_id,
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "choices" in body
        assert body["choices"][0]["message"]["content"] == "fake answer"
    finally:
        client.app.dependency_overrides.pop(get_llm_client, None)  # type: ignore[attr-defined]
