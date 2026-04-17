from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from api.models import FTDatasetRecord, FTDatasetRowRecord, FTDatasetVersionRecord

SUPPORTED_REAL_TRAINING_TASK_TYPES = {
    "instruction_sft",
    "chat_sft",
    "prompt_completion",
}
ALLOWED_TRAINING_SPLITS = {"train", "val", "test"}


@dataclass
class FormattedTrainingRow:
    row_id: int
    split: str
    prompt_text: str
    completion_text: str
    text: str
    messages: list[dict[str, str]]
    task_type: str
    warnings: list[str]


@dataclass
class DatasetExportResult:
    dataset_version_id: str
    dataset_id: str
    task_type: str
    export_dir: str
    train_file: str | None
    val_file: str | None
    test_file: str | None
    all_rows_file: str
    summary_file: str
    row_counts: dict[str, int]
    warnings: list[str]
    format_summary: dict[str, Any]


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).strip()


def _instruction_prompt(input_json: Any) -> str:
    if isinstance(input_json, dict):
        instruction = _as_text(input_json.get("instruction"))
        input_text = _as_text(input_json.get("input"))
        context_text = _as_text(input_json.get("context"))
        parts = [part for part in [instruction, input_text, context_text] if part]
        return "\n\n".join(parts).strip()
    return _as_text(input_json)


def _instruction_completion(target_json: Any) -> str:
    if isinstance(target_json, dict):
        return _as_text(
            target_json.get("output")
            or target_json.get("response")
            or target_json.get("answer")
            or target_json
        )
    return _as_text(target_json)


def _chat_messages(input_json: Any, target_json: Any) -> list[dict[str, str]]:
    warnings: list[str] = []
    messages: list[dict[str, str]] = []
    if isinstance(input_json, list):
        for item in input_json:
            if not isinstance(item, dict):
                continue
            role = _as_text(item.get("role")) or "user"
            content = _as_text(item.get("content"))
            if content:
                messages.append({"role": role, "content": content})
    elif isinstance(input_json, dict):
        role = _as_text(input_json.get("role")) or "user"
        content = _as_text(input_json.get("content") or input_json)
        if content:
            messages.append({"role": role, "content": content})
    else:
        text = _as_text(input_json)
        if text:
            warnings.append(
                "chat_sft input_json was coerced into a single user message"
            )
            messages.append({"role": "user", "content": text})

    assistant_text = _instruction_completion(target_json)
    if assistant_text:
        messages.append({"role": "assistant", "content": assistant_text})
    return messages


def _format_row(task_type: str, row: FTDatasetRowRecord) -> FormattedTrainingRow:
    warnings: list[str] = []
    if task_type == "instruction_sft":
        prompt_text = _instruction_prompt(row.input_json)
        completion_text = _instruction_completion(row.target_json)
        messages = [
            {"role": "user", "content": prompt_text},
            {"role": "assistant", "content": completion_text},
        ]
    elif task_type == "chat_sft":
        messages = _chat_messages(row.input_json, row.target_json)
        prompt_text = "\n".join(
            f"{item['role']}: {item['content']}"
            for item in messages
            if item["role"] != "assistant"
        ).strip()
        completion_text = next(
            (
                item["content"]
                for item in reversed(messages)
                if item["role"] == "assistant"
            ),
            "",
        )
    elif task_type == "prompt_completion":
        prompt_text = _as_text(
            row.input_json.get("prompt")
            if isinstance(row.input_json, dict)
            else row.input_json
        )
        completion_text = _as_text(
            row.target_json.get("completion")
            if isinstance(row.target_json, dict)
            else row.target_json
        )
        messages = [
            {"role": "user", "content": prompt_text},
            {"role": "assistant", "content": completion_text},
        ]
    else:
        raise ValueError(f"unsupported task_type for formatting: {task_type}")

    if not prompt_text:
        raise ValueError(f"row {row.id} is missing prompt text after formatting")
    if not completion_text:
        raise ValueError(f"row {row.id} is missing completion text after formatting")

    text = f"### Instruction\n{prompt_text}\n\n### Response\n{completion_text}".strip()
    if len(text) > 20000:
        warnings.append(
            "formatted text is very long and may exceed local hardware limits"
        )

    return FormattedTrainingRow(
        row_id=row.id,
        split=row.split,
        prompt_text=prompt_text,
        completion_text=completion_text,
        text=text,
        messages=messages,
        task_type=task_type,
        warnings=warnings,
    )


def ensure_real_training_ready(
    dataset: FTDatasetRecord,
    version: FTDatasetVersionRecord,
    rows: list[FTDatasetRowRecord],
    *,
    require_locked: bool,
) -> None:
    if dataset.task_type not in SUPPORTED_REAL_TRAINING_TASK_TYPES:
        raise ValueError(
            f"unsupported task_type for real training: {dataset.task_type}"
        )
    if version.status == "draft":
        raise ValueError("dataset version must be validated or locked before training")
    if require_locked and version.status != "locked":
        raise ValueError("real training requires a locked dataset version")
    if not rows:
        raise ValueError("dataset version has no rows")
    invalid_rows = [row.id for row in rows if row.validation_status != "valid"]
    if invalid_rows:
        raise ValueError("dataset version contains invalid rows")
    train_rows = [row for row in rows if row.split == "train"]
    if not train_rows:
        raise ValueError("real training requires at least one train row")


def export_dataset_version_for_training(
    dataset: FTDatasetRecord,
    version: FTDatasetVersionRecord,
    rows: list[FTDatasetRowRecord],
    *,
    export_root: Path,
    require_locked: bool = True,
) -> DatasetExportResult:
    ensure_real_training_ready(
        dataset,
        version,
        rows,
        require_locked=require_locked,
    )
    export_root.mkdir(parents=True, exist_ok=True)

    formatted_rows: list[FormattedTrainingRow] = []
    warnings: list[str] = []
    row_counts = {"train": 0, "val": 0, "test": 0, "unlabeled": 0}
    split_payloads: dict[str, list[dict[str, Any]]] = {key: [] for key in row_counts}
    all_payloads: list[dict[str, Any]] = []

    for row in rows:
        formatted = _format_row(dataset.task_type, row)
        formatted_rows.append(formatted)
        warnings.extend(formatted.warnings)
        row_counts[row.split] = row_counts.get(row.split, 0) + 1
        payload = asdict(formatted)
        all_payloads.append(payload)
        split_payloads.setdefault(row.split, []).append(payload)

    all_rows_file = export_root / "all.jsonl"
    all_rows_file.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in all_payloads) + "\n",
        encoding="utf-8",
    )

    def _write_split(name: str) -> str | None:
        items = split_payloads.get(name, [])
        if not items:
            return None
        file_path = export_root / f"{name}.jsonl"
        file_path.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in items) + "\n",
            encoding="utf-8",
        )
        return str(file_path)

    train_file = _write_split("train")
    val_file = _write_split("val")
    test_file = _write_split("test")

    format_summary = {
        "dataset_id": dataset.id,
        "dataset_version_id": version.id,
        "task_type": dataset.task_type,
        "schema_type": dataset.schema_type,
        "status": version.status,
        "row_counts": row_counts,
        "warnings": warnings,
        "supported_for_real_training": dataset.task_type
        in SUPPORTED_REAL_TRAINING_TASK_TYPES,
    }
    summary_file = export_root / "summary.json"
    summary_file.write_text(json.dumps(format_summary, indent=2), encoding="utf-8")

    return DatasetExportResult(
        dataset_version_id=version.id,
        dataset_id=dataset.id,
        task_type=dataset.task_type,
        export_dir=str(export_root),
        train_file=train_file,
        val_file=val_file,
        test_file=test_file,
        all_rows_file=str(all_rows_file),
        summary_file=str(summary_file),
        row_counts=row_counts,
        warnings=warnings,
        format_summary=format_summary,
    )
