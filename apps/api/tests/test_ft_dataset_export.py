from __future__ import annotations

import json

from api.models import FTDatasetRecord, FTDatasetRowRecord, FTDatasetVersionRecord
from api.services.fine_tuning.dataset_formatters import (
    export_dataset_version_for_training,
)


def test_export_dataset_version_for_instruction_sft(tmp_path) -> None:
    dataset = FTDatasetRecord(
        id="ft-dataset-1",
        name="Instruction demo",
        task_type="instruction_sft",
        schema_type="json",
    )
    version = FTDatasetVersionRecord(
        id="ft-version-1",
        dataset_id=dataset.id,
        version_label="v1",
        status="locked",
    )
    rows = [
        FTDatasetRowRecord(
            id=1,
            dataset_version_id=version.id,
            split="train",
            input_json={"instruction": "summarize", "input": "shift handover"},
            target_json={"output": "short summary"},
            metadata_json={},
            validation_status="valid",
        ),
        FTDatasetRowRecord(
            id=2,
            dataset_version_id=version.id,
            split="val",
            input_json={"instruction": "classify", "input": "alarm"},
            target_json={"output": "critical"},
            metadata_json={},
            validation_status="valid",
        ),
    ]

    result = export_dataset_version_for_training(
        dataset,
        version,
        rows,
        export_root=tmp_path / "dataset_export",
    )

    assert result.row_counts["train"] == 1
    assert result.row_counts["val"] == 1
    assert result.train_file is not None
    train_payload = json.loads(
        (tmp_path / "dataset_export" / "train.jsonl").read_text().splitlines()[0]
    )
    assert train_payload["prompt_text"] == "summarize\n\nshift handover"
    assert train_payload["completion_text"] == "short summary"


def test_export_dataset_version_requires_locked_trainable_rows(tmp_path) -> None:
    dataset = FTDatasetRecord(
        id="ft-dataset-1",
        name="Instruction demo",
        task_type="instruction_sft",
        schema_type="json",
    )
    version = FTDatasetVersionRecord(
        id="ft-version-1",
        dataset_id=dataset.id,
        version_label="v1",
        status="validated",
    )
    rows = [
        FTDatasetRowRecord(
            id=1,
            dataset_version_id=version.id,
            split="train",
            input_json={"instruction": "summarize", "input": "shift handover"},
            target_json={"output": "short summary"},
            metadata_json={},
            validation_status="invalid",
        )
    ]

    try:
        export_dataset_version_for_training(
            dataset,
            version,
            rows,
            export_root=tmp_path / "dataset_export",
        )
    except ValueError as exc:
        assert "locked" in str(exc) or "invalid" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError(
            "expected dataset export to fail for invalid/unlocked rows"
        )
