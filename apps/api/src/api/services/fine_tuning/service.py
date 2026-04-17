from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models import FTDatasetRecord, FTDatasetRowRecord, FTDatasetVersionRecord

ALLOWED_TASK_TYPES = {"instruction_sft", "chat_sft", "prompt_completion"}
ALLOWED_VERSION_STATUSES = {"draft", "validated", "locked"}
ALLOWED_ROW_SPLITS = {"train", "val", "test", "unlabeled"}


def _next_prefixed_id(session: Session, model: type, prefix: str) -> str:
    next_value = 1
    for existing_id in session.scalars(select(model.id)).all():
        suffix = str(existing_id).replace(f"{prefix}-", "", 1)
        if suffix.isdigit():
            next_value = max(next_value, int(suffix) + 1)
    return f"{prefix}-{next_value}"


def _validate_split_ratios(train: float, val: float, test: float) -> None:
    total = round(float(train) + float(val) + float(test), 4)
    if total > 1.0001:
        raise ValueError("train/val/test split ratios must not exceed 1.0 in total")


def _validate_row(
    task_type: str, input_json: Any, target_json: Any
) -> tuple[str, str | None]:
    if input_json in (None, "", [], {}):
        return "invalid", "input_json is required"
    if target_json in (None, "", [], {}):
        return "invalid", "target_json is required"

    if task_type == "chat_sft":
        if not isinstance(input_json, (list, dict)):
            return "invalid", "chat_sft input_json must be a list or object"
    elif task_type in {"instruction_sft", "prompt_completion"}:
        if not isinstance(input_json, (dict, list, str)):
            return "invalid", "input_json must be json-compatible"
        if not isinstance(target_json, (dict, list, str)):
            return "invalid", "target_json must be json-compatible"
    else:
        return "invalid", f"unsupported task_type: {task_type}"

    return "valid", None


def _split_counts(rows: list[FTDatasetRowRecord]) -> dict[str, int]:
    counts = {key: 0 for key in sorted(ALLOWED_ROW_SPLITS)}
    for row in rows:
        counts[row.split] = counts.get(row.split, 0) + 1
    return counts


def _serialize_row(row: FTDatasetRowRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "dataset_version_id": row.dataset_version_id,
        "split": row.split,
        "input_json": row.input_json,
        "target_json": row.target_json,
        "metadata_json": row.metadata_json,
        "validation_status": row.validation_status,
        "validation_error": row.validation_error,
        "created_at": row.created_at.isoformat()
        if row.created_at is not None
        else None,
        "updated_at": row.updated_at.isoformat()
        if row.updated_at is not None
        else None,
    }


def _serialize_version(
    version: FTDatasetVersionRecord, rows: list[FTDatasetRowRecord]
) -> dict[str, Any]:
    valid_count = sum(1 for row in rows if row.validation_status == "valid")
    invalid_count = sum(1 for row in rows if row.validation_status == "invalid")
    return {
        "id": version.id,
        "dataset_id": version.dataset_id,
        "version_label": version.version_label,
        "status": version.status,
        "row_count": version.row_count,
        "train_split_ratio": version.train_split_ratio,
        "val_split_ratio": version.val_split_ratio,
        "test_split_ratio": version.test_split_ratio,
        "created_at": version.created_at.isoformat()
        if version.created_at is not None
        else None,
        "updated_at": version.updated_at.isoformat()
        if version.updated_at is not None
        else None,
        "row_summary": {
            "total": len(rows),
            "valid": valid_count,
            "invalid": invalid_count,
            "by_split": _split_counts(rows),
        },
    }


def _serialize_dataset(
    dataset: FTDatasetRecord,
    versions: list[FTDatasetVersionRecord],
    version_rows: dict[str, list[FTDatasetRowRecord]],
) -> dict[str, Any]:
    ordered_versions = sorted(
        versions, key=lambda item: (item.created_at, item.id), reverse=True
    )
    return {
        "id": dataset.id,
        "name": dataset.name,
        "task_type": dataset.task_type,
        "schema_type": dataset.schema_type,
        "description": dataset.description,
        "current_version_id": dataset.current_version_id,
        "created_at": dataset.created_at.isoformat()
        if dataset.created_at is not None
        else None,
        "updated_at": dataset.updated_at.isoformat()
        if dataset.updated_at is not None
        else None,
        "versions": [
            _serialize_version(version, version_rows.get(version.id, []))
            for version in ordered_versions
        ],
    }


def list_datasets(session: Session) -> list[dict[str, Any]]:
    datasets = session.scalars(
        select(FTDatasetRecord).order_by(
            FTDatasetRecord.created_at.desc(), FTDatasetRecord.id.desc()
        )
    ).all()
    versions = session.scalars(select(FTDatasetVersionRecord)).all()
    rows = session.scalars(select(FTDatasetRowRecord)).all()
    rows_by_version: dict[str, list[FTDatasetRowRecord]] = {}
    for row in rows:
        rows_by_version.setdefault(row.dataset_version_id, []).append(row)
    versions_by_dataset: dict[str, list[FTDatasetVersionRecord]] = {}
    for version in versions:
        versions_by_dataset.setdefault(version.dataset_id, []).append(version)
    return [
        _serialize_dataset(
            dataset, versions_by_dataset.get(dataset.id, []), rows_by_version
        )
        for dataset in datasets
    ]


def get_dataset(session: Session, dataset_id: str) -> dict[str, Any] | None:
    dataset = session.get(FTDatasetRecord, dataset_id)
    if dataset is None:
        return None
    versions = session.scalars(
        select(FTDatasetVersionRecord).where(
            FTDatasetVersionRecord.dataset_id == dataset_id
        )
    ).all()
    rows = (
        session.scalars(
            select(FTDatasetRowRecord).where(
                FTDatasetRowRecord.dataset_version_id.in_(
                    [version.id for version in versions]
                )
            )
        ).all()
        if versions
        else []
    )
    rows_by_version: dict[str, list[FTDatasetRowRecord]] = {}
    for row in rows:
        rows_by_version.setdefault(row.dataset_version_id, []).append(row)
    return _serialize_dataset(dataset, versions, rows_by_version)


def create_dataset(
    session: Session,
    *,
    name: str,
    task_type: str,
    schema_type: str,
    description: str | None,
) -> dict[str, Any]:
    normalized_task_type = task_type.strip()
    if normalized_task_type not in ALLOWED_TASK_TYPES:
        raise ValueError("unsupported task_type")
    dataset = FTDatasetRecord(
        id=_next_prefixed_id(session, FTDatasetRecord, "ft-dataset"),
        name=name.strip(),
        task_type=normalized_task_type,
        schema_type=schema_type.strip() or "json",
        description=description.strip() if description else None,
        updated_at=datetime.now(timezone.utc),
    )
    session.add(dataset)
    session.commit()
    return get_dataset(session, dataset.id) or {"id": dataset.id}


def create_dataset_version(
    session: Session,
    *,
    dataset_id: str,
    version_label: str,
    train_split_ratio: float,
    val_split_ratio: float,
    test_split_ratio: float,
) -> dict[str, Any]:
    dataset = session.get(FTDatasetRecord, dataset_id)
    if dataset is None:
        raise KeyError(dataset_id)
    _validate_split_ratios(train_split_ratio, val_split_ratio, test_split_ratio)
    version = FTDatasetVersionRecord(
        id=_next_prefixed_id(session, FTDatasetVersionRecord, "ft-version"),
        dataset_id=dataset_id,
        version_label=version_label.strip(),
        train_split_ratio=float(train_split_ratio),
        val_split_ratio=float(val_split_ratio),
        test_split_ratio=float(test_split_ratio),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(version)
    dataset.current_version_id = version.id
    dataset.updated_at = datetime.now(timezone.utc)
    session.commit()
    return get_dataset_version(session, version.id) or {"id": version.id}


def get_dataset_version(session: Session, version_id: str) -> dict[str, Any] | None:
    version = session.get(FTDatasetVersionRecord, version_id)
    if version is None:
        return None
    rows = session.scalars(
        select(FTDatasetRowRecord)
        .where(FTDatasetRowRecord.dataset_version_id == version_id)
        .order_by(FTDatasetRowRecord.id.asc())
    ).all()
    payload = _serialize_version(version, rows)
    payload["rows"] = [_serialize_row(row) for row in rows]
    return payload


def list_dataset_rows(session: Session, version_id: str) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(FTDatasetRowRecord)
        .where(FTDatasetRowRecord.dataset_version_id == version_id)
        .order_by(FTDatasetRowRecord.id.asc())
    ).all()
    return [_serialize_row(row) for row in rows]


def add_dataset_rows(
    session: Session,
    *,
    version_id: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    version = session.get(FTDatasetVersionRecord, version_id)
    if version is None:
        raise KeyError(version_id)
    if version.status == "locked":
        raise ValueError("locked dataset versions cannot accept new rows")
    dataset = session.get(FTDatasetRecord, version.dataset_id)
    assert dataset is not None

    now = datetime.now(timezone.utc)
    for item in rows:
        split = str(item.get("split") or "unlabeled").strip() or "unlabeled"
        if split not in ALLOWED_ROW_SPLITS:
            raise ValueError(f"unsupported row split: {split}")
        validation_status, validation_error = _validate_row(
            dataset.task_type,
            item.get("input_json"),
            item.get("target_json"),
        )
        session.add(
            FTDatasetRowRecord(
                dataset_version_id=version_id,
                split=split,
                input_json=item.get("input_json"),
                target_json=item.get("target_json"),
                metadata_json=item.get("metadata_json")
                if isinstance(item.get("metadata_json"), dict)
                else {},
                validation_status=validation_status,
                validation_error=validation_error,
                updated_at=now,
            )
        )

    session.flush()
    persisted_rows = session.scalars(
        select(FTDatasetRowRecord).where(
            FTDatasetRowRecord.dataset_version_id == version_id
        )
    ).all()
    version.row_count = len(persisted_rows)
    version.updated_at = now
    session.commit()
    return get_dataset_version(session, version_id) or {"id": version_id}


def set_dataset_version_status(
    session: Session, *, version_id: str, status: str
) -> dict[str, Any]:
    version = session.get(FTDatasetVersionRecord, version_id)
    if version is None:
        raise KeyError(version_id)
    normalized_status = status.strip()
    if normalized_status not in ALLOWED_VERSION_STATUSES:
        raise ValueError("unsupported dataset version status")
    rows = session.scalars(
        select(FTDatasetRowRecord).where(
            FTDatasetRowRecord.dataset_version_id == version_id
        )
    ).all()
    if normalized_status == "validated" and any(
        row.validation_status != "valid" for row in rows
    ):
        raise ValueError("all rows must be valid before a version can be validated")
    if normalized_status == "locked" and version.status != "validated":
        raise ValueError("dataset version must be validated before it can be locked")
    version.status = normalized_status
    version.updated_at = datetime.now(timezone.utc)
    session.commit()
    return get_dataset_version(session, version_id) or {"id": version_id}
