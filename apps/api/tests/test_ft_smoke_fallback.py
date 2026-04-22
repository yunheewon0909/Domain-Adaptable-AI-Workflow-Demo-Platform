from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from api.config import get_settings
from api.services.fine_tuning.dataset_formatters import DatasetExportResult
from api.services.fine_tuning.trainer import (
    DETERMINISTIC_SMOKE_TRAINER_MODEL_NAME,
    run_training_backend,
)


def _settings(**overrides):
    return replace(
        get_settings(),
        training_device="cpu",
        training_allow_cpu=True,
        ft_default_training_method="sft_lora",
        ft_trainer_backend="local_peft",
        ft_allow_smoke_fallback=True,
        ft_smoke_fallback_backend="deterministic_smoke",
        ft_trainer_model_map_json=(
            '{"qwen2.5:7b-instruct-q4_K_M":"hf-internal/testing-tiny-random-gpt2"}'
        ),
        **overrides,
    )


def _export_result(tmp_path: Path) -> DatasetExportResult:
    export_dir = tmp_path / "dataset_export"
    export_dir.mkdir(parents=True, exist_ok=True)
    train_file = export_dir / "train.jsonl"
    train_file.write_text('{"text": "example"}\n', encoding="utf-8")
    all_rows_file = export_dir / "all_rows.jsonl"
    all_rows_file.write_text('{"text": "example"}\n', encoding="utf-8")
    summary_file = export_dir / "summary.json"
    summary_file.write_text('{"row_counts": {"train": 1}}', encoding="utf-8")
    return DatasetExportResult(
        dataset_version_id="ft-version-1",
        dataset_id="ft-dataset-1",
        task_type="instruction_sft",
        export_dir=str(export_dir),
        train_file=str(train_file),
        val_file=None,
        test_file=None,
        all_rows_file=str(all_rows_file),
        summary_file=str(summary_file),
        row_counts={"train": 1, "val": 0, "test": 0, "unlabeled": 0},
        warnings=[],
        format_summary={"task_type": "instruction_sft", "row_counts": {"train": 1}},
    )


def test_run_training_backend_uses_deterministic_smoke_fallback_for_hf_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "api.services.fine_tuning.trainer._require_training_dependencies",
        lambda: None,
    )

    def _raise_hf_resolution_failure(*args, **kwargs):
        raise RuntimeError(
            "RepositoryNotFoundError: 404 Client Error while resolving model files from "
            "https://huggingface.co/hf-internal/testing-tiny-random-gpt2 via from_pretrained"
        )

    monkeypatch.setattr(
        "api.services.fine_tuning.trainer._run_local_peft_training",
        _raise_hf_resolution_failure,
    )

    result = run_training_backend(
        _export_result(tmp_path),
        base_model_name="qwen2.5:7b-instruct-q4_K_M",
        training_method="sft_lora",
        hyperparams_json={
            "smoke_test": True,
            "trainer_model_name": "hf-internal/testing-tiny-random-gpt2",
        },
        settings=_settings(),
        output_dir=tmp_path / "trainer_output",
    )

    assert result.trainer_backend == "local_peft+smoke_fallback"
    assert result.trainer_model_name == DETERMINISTIC_SMOKE_TRAINER_MODEL_NAME
    assert Path(result.adapter_dir, "adapter_config.json").exists()
    assert Path(result.report_path).exists()
    assert Path(result.logs_path).exists()


def test_run_training_backend_does_not_fallback_for_non_hf_resolution_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "api.services.fine_tuning.trainer._require_training_dependencies",
        lambda: None,
    )

    def _raise_non_hf_resolution_failure(*args, **kwargs):
        raise RuntimeError("failed to resolve local artifact directory permissions")

    monkeypatch.setattr(
        "api.services.fine_tuning.trainer._run_local_peft_training",
        _raise_non_hf_resolution_failure,
    )

    with pytest.raises(
        RuntimeError, match="failed to resolve local artifact directory permissions"
    ):
        run_training_backend(
            _export_result(tmp_path),
            base_model_name="qwen2.5:7b-instruct-q4_K_M",
            training_method="sft_lora",
            hyperparams_json={
                "smoke_test": True,
                "trainer_model_name": "hf-internal/testing-tiny-random-gpt2",
            },
            settings=_settings(),
            output_dir=tmp_path / "trainer_output_non_hf",
        )
