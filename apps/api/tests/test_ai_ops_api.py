from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlalchemy.orm import Session

from api.db import get_engine
from api.dependencies import get_llm_client
from api.main import app
from api.config import get_settings
from api.models import (
    FTTrainingJobRecord,
    JobRecord,
    ModelRegistryRecord,
    RAGDocumentRecord,
)
from api.services.fine_tuning.trainer import TrainingArtifacts
from api.services.model_registry.service import complete_training_job


class FakeLLMClient:
    def generate_answer(
        self,
        *,
        question: str,
        context: str,
        model: str | None = None,
        temperature: float = 0,
        max_tokens: int | None = None,
    ):
        class _Result:
            def __init__(self) -> None:
                self.answer = f"answer::{question}::{model}"
                self.model = model or "default-model"
                self.used_fallback = False

        return _Result()


def _create_pdf_bytes(text: str) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.add_metadata({"/Title": text})
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _build_fake_training_artifacts(tmp_path: Path) -> TrainingArtifacts:
    adapter_dir = tmp_path / "adapter"
    adapter_dir.mkdir(parents=True, exist_ok=True)
    (adapter_dir / "adapter_config.json").write_text("{}", encoding="utf-8")
    (adapter_dir / "adapter_model.safetensors").write_text("stub", encoding="utf-8")
    report_path = tmp_path / "training_report.json"
    report_path.write_text(json.dumps({"ok": True}), encoding="utf-8")
    logs_path = tmp_path / "training.log"
    logs_path.write_text("training complete\n", encoding="utf-8")
    return TrainingArtifacts(
        adapter_dir=str(adapter_dir),
        report_path=str(report_path),
        merged_model_dir=None,
        logs_path=str(logs_path),
        metrics={"train_runtime": 0.1, "train_loss": 0.01},
        evaluation={"status": "not_run", "baseline_comparison": "not_implemented"},
        trainer_backend="local_peft",
        trainer_model_name="hf-internal/testing-tiny-random-gpt2",
        device="cpu",
    )


def test_ft_dataset_version_and_rows_flow(client: TestClient) -> None:
    dataset_response = client.post(
        "/ft-datasets",
        json={
            "name": "Instruction tuning demo",
            "task_type": "instruction_sft",
            "schema_type": "json",
            "description": "demo dataset",
        },
    )
    assert dataset_response.status_code == 201
    dataset_id = dataset_response.json()["id"]

    version_response = client.post(
        f"/ft-datasets/{dataset_id}/versions",
        json={
            "version_label": "v1",
            "train_split_ratio": 0.7,
            "val_split_ratio": 0.2,
            "test_split_ratio": 0.1,
        },
    )
    assert version_response.status_code == 201
    version_id = version_response.json()["id"]

    rows_response = client.post(
        f"/ft-dataset-versions/{version_id}/rows",
        json={
            "rows": [
                {
                    "split": "train",
                    "input_json": {
                        "instruction": "summarize",
                        "input": "plant outage note",
                    },
                    "target_json": {"output": "summary"},
                    "metadata_json": {"source": "manual"},
                },
                {
                    "split": "val",
                    "input_json": {"instruction": "classify"},
                    "target_json": None,
                    "metadata_json": {"source": "invalid-row"},
                },
            ]
        },
    )
    assert rows_response.status_code == 201
    payload = rows_response.json()
    assert payload["row_summary"]["total"] == 2
    assert payload["row_summary"]["valid"] == 1
    assert payload["row_summary"]["invalid"] == 1

    validate_response = client.post(
        f"/ft-dataset-versions/{version_id}/status", json={"status": "validated"}
    )
    assert validate_response.status_code == 400

    rows_list = client.get(f"/ft-dataset-versions/{version_id}/rows")
    assert rows_list.status_code == 200
    assert rows_list.json()[1]["validation_status"] == "invalid"


def test_ft_dataset_version_cannot_validate_without_rows(client: TestClient) -> None:
    dataset_id = client.post(
        "/ft-datasets",
        json={
            "name": "Empty validation demo",
            "task_type": "instruction_sft",
            "schema_type": "json",
        },
    ).json()["id"]
    version_id = client.post(
        f"/ft-datasets/{dataset_id}/versions",
        json={"version_label": "v1"},
    ).json()["id"]

    response = client.post(
        f"/ft-dataset-versions/{version_id}/status", json={"status": "validated"}
    )

    assert response.status_code == 400
    assert "at least one row" in response.json()["detail"]


def test_ft_dataset_version_summary_endpoint(client: TestClient) -> None:
    dataset_id = client.post(
        "/ft-datasets",
        json={
            "name": "Summary demo",
            "task_type": "instruction_sft",
            "schema_type": "json",
        },
    ).json()["id"]
    version_id = client.post(
        f"/ft-datasets/{dataset_id}/versions",
        json={"version_label": "v1"},
    ).json()["id"]
    client.post(
        f"/ft-dataset-versions/{version_id}/rows",
        json={
            "rows": [
                {
                    "split": "train",
                    "input_json": {"instruction": "summarize", "input": "alpha"},
                    "target_json": {"output": "beta"},
                }
            ]
        },
    )

    response = client.get(f"/ft-dataset-versions/{version_id}/summary")
    assert response.status_code == 200
    assert response.json()["id"] == version_id
    assert "rows" not in response.json()


def test_real_training_requires_locked_dataset_version(client: TestClient) -> None:
    dataset_id = client.post(
        "/ft-datasets",
        json={
            "name": "Locked demo",
            "task_type": "instruction_sft",
            "schema_type": "json",
        },
    ).json()["id"]
    version_id = client.post(
        f"/ft-datasets/{dataset_id}/versions",
        json={"version_label": "v1"},
    ).json()["id"]
    client.post(
        f"/ft-dataset-versions/{version_id}/rows",
        json={
            "rows": [
                {
                    "split": "train",
                    "input_json": {"instruction": "summarize", "input": "alpha"},
                    "target_json": {"output": "beta"},
                }
            ]
        },
    )
    client.post(
        f"/ft-dataset-versions/{version_id}/status", json={"status": "validated"}
    )

    response = client.post(
        "/ft-training-jobs",
        json={
            "dataset_version_id": version_id,
            "base_model_name": "qwen2.5:7b-instruct-q4_K_M",
            "training_method": "sft_lora",
            "hyperparams_json": {
                "trainer_model_name": "hf-internal/testing-tiny-random-gpt2"
            },
        },
    )
    assert response.status_code == 400
    assert "locked dataset version" in response.json()["detail"]


def test_training_job_model_registry_and_inference_flow(
    client: TestClient, monkeypatch, tmp_path: Path
) -> None:
    app.dependency_overrides[get_llm_client] = lambda: FakeLLMClient()
    try:
        monkeypatch.setenv("MODEL_ARTIFACT_DIR", str(tmp_path / "model_artifacts"))
        monkeypatch.setenv("OLLAMA_PUBLISH_ENABLED", "true")
        monkeypatch.setenv("OLLAMA_MODEL_NAMESPACE", "demo")
        get_settings.cache_clear()

        def _fake_run_training_backend(*args, **kwargs):
            return _build_fake_training_artifacts(tmp_path / "trainer_output")

        monkeypatch.setattr(
            "api.services.model_registry.service.run_training_backend",
            _fake_run_training_backend,
        )

        dataset_id = client.post(
            "/ft-datasets",
            json={
                "name": "Chat tuning demo",
                "task_type": "chat_sft",
                "schema_type": "json",
                "description": "chat demo",
            },
        ).json()["id"]
        version_id = client.post(
            f"/ft-datasets/{dataset_id}/versions",
            json={"version_label": "v1"},
        ).json()["id"]
        add_rows = client.post(
            f"/ft-dataset-versions/{version_id}/rows",
            json={
                "rows": [
                    {
                        "split": "train",
                        "input_json": [{"role": "user", "content": "hello"}],
                        "target_json": {"response": "hi"},
                    }
                ]
            },
        )
        assert add_rows.status_code == 201
        validated = client.post(
            f"/ft-dataset-versions/{version_id}/status", json={"status": "validated"}
        )
        assert validated.status_code == 200
        locked = client.post(
            f"/ft-dataset-versions/{version_id}/status", json={"status": "locked"}
        )
        assert locked.status_code == 200

        training_response = client.post(
            "/ft-training-jobs",
            json={
                "dataset_version_id": version_id,
                "base_model_name": "qwen2.5:7b-instruct-q4_K_M",
                "training_method": "sft_lora",
                "hyperparams_json": {
                    "epochs": 1,
                    "trainer_model_name": "hf-internal/testing-tiny-random-gpt2",
                },
            },
        )
        assert training_response.status_code == 202
        training_job_id = training_response.json()["id"]
        backing_job_id = training_response.json()["backing_job_id"]

        with Session(get_engine()) as session:
            training_job = session.get(FTTrainingJobRecord, training_job_id)
            assert training_job is not None
            assert training_job.backing_job_id == backing_job_id
            queue_job = session.get(JobRecord, backing_job_id)
            assert queue_job is not None
            assert queue_job.type == "ft_train_model"
            complete_training_job(session, training_job_id=training_job_id)

        training_detail = client.get(f"/ft-training-jobs/{training_job_id}")
        assert training_detail.status_code == 200
        assert training_detail.json()["status"] == "succeeded"
        assert training_detail.json()["trainer_backend"] == "local_peft"
        assert (
            training_detail.json()["trainer_model_name"]
            == "hf-internal/testing-tiny-random-gpt2"
        )
        assert training_detail.json()["device"] == "cpu"
        assert len(training_detail.json()["artifacts"]) >= 4
        assert len(training_detail.json()["registered_models"]) == 1
        model_id = training_detail.json()["registered_models"][0]["id"]
        assert (
            training_detail.json()["registered_models"][0]["status"] == "artifact_ready"
        )
        assert (
            training_detail.json()["registered_models"][0]["publish_status"]
            == "publish_ready"
        )
        assert (
            training_detail.json()["registered_models"][0]["serving_model_name"] is None
        )
        assert (
            training_detail.json()["registered_models"][0]["readiness"]["selectable"]
            is False
        )
        assert training_detail.json()["artifact_validation"]["artifact_valid"] is True
        assert training_detail.json()["lineage_warning"]
        assert training_detail.json()["publish_readiness"]["runtime_ready"] is False

        models_response = client.get("/models")
        assert models_response.status_code == 200
        assert any(item["id"] == model_id for item in models_response.json())

        blocked_inference_response = client.post(
            "/inference/run",
            json={"prompt": "generate summary", "model_id": model_id},
        )
        assert blocked_inference_response.status_code == 404

        publish_response = client.post(f"/ft-training-jobs/{training_job_id}/publish")
        assert publish_response.status_code == 200
        assert publish_response.json()["publish_status"] == "publish_ready"
        assert publish_response.json()["serving_model_name"] is None
        assert (
            publish_response.json()["candidate_published_model_name"]
            == f"demo/{training_job_id}"
        )
        assert publish_response.json()["readiness"]["runtime_ready"] is False
        assert any(
            "Automatic Ollama import is not implemented" in warning
            for warning in publish_response.json()["warnings"]
        )

        lineage_response = client.get(f"/models/{model_id}/lineage")
        assert lineage_response.status_code == 200
        assert (
            lineage_response.json()["lineage_json"]["dataset_version_id"] == version_id
        )
        assert (
            lineage_response.json()["trainer_model_name"]
            == "hf-internal/testing-tiny-random-gpt2"
        )
        assert (
            lineage_response.json()["candidate_published_model_name"]
            == f"demo/{training_job_id}"
        )

        artifact_id = training_detail.json()["artifacts"][0]["id"]
        artifact_response = client.get(f"/ft-model-artifacts/{artifact_id}")
        assert artifact_response.status_code == 200

        logs_response = client.get(f"/ft-training-jobs/{training_job_id}/logs")
        assert logs_response.status_code == 200

        inference_response = client.post(
            "/inference/run",
            json={"prompt": "generate summary", "model_id": model_id},
        )
        assert inference_response.status_code == 404

        ambiguous_inference_response = client.post(
            "/inference/run",
            json={
                "prompt": "generate summary",
                "model_id": model_id,
                "ollama_model_name": "qwen2.5:3b-instruct-q4_K_M",
            },
        )
        assert ambiguous_inference_response.status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_publish_disabled_returns_truthful_artifact_ready_status(
    client: TestClient, monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MODEL_ARTIFACT_DIR", str(tmp_path / "model_artifacts"))
    monkeypatch.setenv("OLLAMA_PUBLISH_ENABLED", "false")
    monkeypatch.setenv("OLLAMA_MODEL_NAMESPACE", "demo")
    get_settings.cache_clear()

    def _fake_run_training_backend(*args, **kwargs):
        return _build_fake_training_artifacts(tmp_path / "trainer_output_disabled")

    monkeypatch.setattr(
        "api.services.model_registry.service.run_training_backend",
        _fake_run_training_backend,
    )

    dataset_id = client.post(
        "/ft-datasets",
        json={
            "name": "Publish disabled demo",
            "task_type": "instruction_sft",
            "schema_type": "json",
        },
    ).json()["id"]
    version_id = client.post(
        f"/ft-datasets/{dataset_id}/versions",
        json={"version_label": "v1"},
    ).json()["id"]
    client.post(
        f"/ft-dataset-versions/{version_id}/rows",
        json={
            "rows": [
                {
                    "split": "train",
                    "input_json": {"instruction": "summarize", "input": "alpha"},
                    "target_json": {"output": "beta"},
                }
            ]
        },
    )
    client.post(
        f"/ft-dataset-versions/{version_id}/status", json={"status": "validated"}
    )
    client.post(f"/ft-dataset-versions/{version_id}/status", json={"status": "locked"})
    training_job_id = client.post(
        "/ft-training-jobs",
        json={
            "dataset_version_id": version_id,
            "base_model_name": "qwen2.5:7b-instruct-q4_K_M",
            "training_method": "sft_lora",
            "hyperparams_json": {
                "trainer_model_name": "hf-internal/testing-tiny-random-gpt2"
            },
        },
    ).json()["id"]

    with Session(get_engine()) as session:
        complete_training_job(session, training_job_id=training_job_id)

    publish_response = client.post(f"/ft-training-jobs/{training_job_id}/publish")
    assert publish_response.status_code == 200
    assert publish_response.json()["status"] == "artifact_ready"
    assert publish_response.json()["publish_status"] == "publish_ready"
    assert publish_response.json()["readiness"]["selectable"] is False
    assert (
        publish_response.json()["candidate_published_model_name"]
        == f"demo/{training_job_id}"
    )


def test_rag_collection_document_and_preview_flow(client: TestClient) -> None:
    collection_response = client.post(
        "/rag-collections",
        json={"name": "Maintenance docs", "description": "RAG demo docs"},
    )
    assert collection_response.status_code == 201
    collection_id = collection_response.json()["id"]

    txt_upload = client.post(
        f"/rag-collections/{collection_id}/documents",
        files={
            "file": ("note.txt", b"maintenance automation diagnostics", "text/plain")
        },
    )
    assert txt_upload.status_code == 201
    assert txt_upload.json()["status"] == "parsed"

    md_upload = client.post(
        f"/rag-collections/{collection_id}/documents",
        files={
            "file": (
                "guide.md",
                b"# Guide\nplant maintenance checklist",
                "text/markdown",
            )
        },
    )
    assert md_upload.status_code == 201
    assert "maintenance checklist" in md_upload.json()["text_preview"]

    pdf_upload = client.post(
        f"/rag-collections/{collection_id}/documents",
        files={
            "file": (
                "spec.pdf",
                _create_pdf_bytes("maintenance pdf title"),
                "application/pdf",
            )
        },
    )
    assert pdf_upload.status_code == 201
    assert pdf_upload.json()["metadata_json"]["parse_method"] in {
        "pypdf",
        "pdf-fallback",
    }

    list_response = client.get(f"/rag-collections/{collection_id}/documents")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 3

    document_id = txt_upload.json()["id"]
    document_detail = client.get(f"/rag-documents/{document_id}")
    assert document_detail.status_code == 200
    assert document_detail.json()["filename"] == "note.txt"

    preview_response = client.post(
        "/rag-retrieval/preview",
        json={
            "collection_id": collection_id,
            "query": "maintenance automation",
            "top_k": 2,
        },
    )
    assert preview_response.status_code == 200
    assert preview_response.json()["results"][0]["filename"] == "note.txt"

    with Session(get_engine()) as session:
        stored_document = session.get(RAGDocumentRecord, document_id)
        assert stored_document is not None
        assert stored_document.status == "parsed"


def test_model_registry_default_entries_are_seeded(client: TestClient) -> None:
    response = client.get("/models")
    assert response.status_code == 200
    models = response.json()
    assert any(item["source_type"] == "base" for item in models)

    with Session(get_engine()) as session:
        registry_rows = session.query(ModelRegistryRecord).all()
        assert registry_rows
