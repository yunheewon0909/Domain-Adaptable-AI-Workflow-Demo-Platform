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
            "base_model_name": "qwen3.5:4b",
            "training_method": "sft_qlora",
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
        trainer_backend = "mlx_qlora"
        trainer_model_name = "hf-internal/testing-tiny-random-gpt2"
        device = "cpu"

    Path(_Artifacts.adapter_dir).mkdir(parents=True, exist_ok=True)
    Path(_Artifacts.adapter_dir, "adapter_config.json").write_text(
        "{}", encoding="utf-8"
    )
    Path(_Artifacts.adapter_dir, "adapters.safetensors").write_text(
        "stub", encoding="utf-8"
    )
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


def test_execute_training_job_fails_when_adapter_artifacts_are_missing(
    client, monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MODEL_ARTIFACT_DIR", str(tmp_path / "artifacts"))

    dataset_id = client.post(
        "/ft-datasets",
        json={
            "name": "Runner validation demo",
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
            "base_model_name": "qwen3.5:4b",
            "training_method": "sft_qlora",
            "hyperparams_json": {
                "trainer_model_name": "hf-internal/testing-tiny-random-gpt2"
            },
        },
    ).json()["id"]

    class _Artifacts:
        adapter_dir = str(tmp_path / "broken-adapter")
        report_path = str(tmp_path / "report.json")
        merged_model_dir = None
        logs_path = str(tmp_path / "training.log")
        metrics = {"train_loss": 0.01}
        evaluation = {"status": "not_run"}
        trainer_backend = "mlx_qlora"
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
        try:
            execute_training_job({"training_job_id": training_job_id}, session=session)
        except RuntimeError as exc:
            assert "training artifacts failed validation" in str(exc)
        else:
            raise AssertionError("expected training artifact validation failure")

    failed_detail = client.get(f"/ft-training-jobs/{training_job_id}")
    assert failed_detail.status_code == 200
    assert failed_detail.json()["status"] == "failed"
    assert failed_detail.json()["error_json"]["phase"] == "packaging"


def test_small_dataset_autoscale_iters_and_lr() -> None:
    """Tiny datasets must get enough passes to imprint, at a gentle LR.

    Regression guard for the "FT answers identically to base" report: a
    9-row run previously resolved to only 18 iters (2 passes), too few to
    move the adapter visibly. It now targets ~6 passes (min 30) while
    keeping the low 1e-5 LR that prevents divergence on small N.
    """
    from api.config import get_settings
    from api.services.fine_tuning.trainer import build_training_config

    settings = get_settings()

    cfg = build_training_config(
        base_model_name="liquid/lfm2.5-1.2b",
        training_method="sft_qlora",
        hyperparams_json={},
        settings=settings,
        train_rows=9,
    )
    assert cfg.mlx_iters == 54  # 9 * 6, within [30, 120]
    assert cfg.learning_rate == 1e-5

    # Floor applies for very tiny sets so they still get real training.
    tiny = build_training_config(
        base_model_name="liquid/lfm2.5-1.2b",
        training_method="sft_qlora",
        hyperparams_json={},
        settings=settings,
        train_rows=2,
    )
    assert tiny.mlx_iters == 30  # max(30, 2 * 6)

    # Explicit user overrides still win.
    override = build_training_config(
        base_model_name="liquid/lfm2.5-1.2b",
        training_method="sft_qlora",
        hyperparams_json={"mlx_iters": 200, "learning_rate": 2e-4},
        settings=settings,
        train_rows=9,
    )
    assert override.mlx_iters == 200
    assert override.learning_rate == 2e-4


def _make_mlx_dir(path: Path, name_or_path: str) -> None:
    """Create a minimal directory that _is_mlx_model_dir() accepts."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "config.json").write_text(
        '{"_name_or_path": "%s"}' % name_or_path, encoding="utf-8"
    )
    (path / "model.safetensors").write_text("stub", encoding="utf-8")


def test_scan_skips_publish_namespace_when_resolving_base(
    monkeypatch, tmp_path: Path
) -> None:
    """Resolving a base model must never pick the platform's own published
    fine-tune.

    Regression for: retraining `liquid/lfm2.5-1.2b` resolved to the previously
    published FT under `~/.lmstudio/models/demo/...` (it fuzzy-matches the base
    name and sorts before `lmstudio-community/`), so the retrain trained on top
    of the old fine-tune instead of the clean base.
    """
    from api.services.fine_tuning import trainer

    models_root = tmp_path / ".lmstudio" / "models"
    # Clean base (the correct target) and a published FT derived from it.
    _make_mlx_dir(
        models_root / "lmstudio-community" / "LFM2.5-1.2B-Instruct-MLX-4bit",
        "lmstudio-community/LFM2.5-1.2B-Instruct-MLX-4bit",
    )
    _make_mlx_dir(
        models_root / "demo" / "lfm2.5-1.2b_Heewon_Platform_-_Final",
        "demo/lfm2.5-1.2b_Heewon_Platform_-_Final",
    )
    monkeypatch.setattr(trainer.Path, "home", classmethod(lambda cls: tmp_path))

    # Without the guard, "demo/" sorts first and would win the fuzzy match.
    leaked = trainer._scan_lmstudio_models_for_key("liquid/lfm2.5-1.2b")
    assert leaked is not None and "demo" in leaked  # documents the old behavior

    resolved = trainer._scan_lmstudio_models_for_key(
        "liquid/lfm2.5-1.2b", exclude_namespace="demo"
    )
    assert resolved is not None
    assert "demo" not in resolved
    assert resolved.endswith("lmstudio-community/LFM2.5-1.2B-Instruct-MLX-4bit")
