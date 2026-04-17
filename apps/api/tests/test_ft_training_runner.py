from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from api.db import get_engine
from api.services.model_registry.job_runner import execute_training_job


def test_execute_training_job_runs_real_path(
    client, monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MODEL_ARTIFACT_DIR", str(tmp_path / "artifacts"))

    dataset_id = client.post(
        "/ft-datasets",
        json={
            "name": "Runner demo",
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

    class _Artifacts:
        adapter_dir = str(tmp_path / "adapter")
        report_path = str(tmp_path / "report.json")
        merged_model_dir = None
        logs_path = str(tmp_path / "training.log")
        metrics = {"train_loss": 0.01}
        evaluation = {"status": "not_run"}
        trainer_backend = "local_peft"
        trainer_model_name = "hf-internal/testing-tiny-random-gpt2"
        device = "cpu"

    Path(_Artifacts.adapter_dir).mkdir(parents=True, exist_ok=True)
    Path(_Artifacts.report_path).write_text("{}", encoding="utf-8")
    Path(_Artifacts.logs_path).write_text("ok\n", encoding="utf-8")
    monkeypatch.setattr(
        "api.services.model_registry.service.run_training_backend",
        lambda *args, **kwargs: _Artifacts(),
    )

    with Session(get_engine()) as session:
        result = execute_training_job(
            {"training_job_id": training_job_id}, session=session
        )

    assert result["training_job_id"] == training_job_id
    assert result["status"] == "succeeded"
    assert len(result["artifacts"]) >= 4
