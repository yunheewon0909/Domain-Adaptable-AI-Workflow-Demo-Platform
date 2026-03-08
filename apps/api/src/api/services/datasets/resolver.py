from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from api.config import resolve_project_path
from api.models import DatasetRecord
from api.services.datasets.registry import get_active_dataset_record, get_dataset_record


class DatasetNotFoundError(KeyError):
    pass


@dataclass(frozen=True)
class ResolvedDataset:
    key: str
    title: str
    domain_type: str
    profile_key: str
    source_dir: Path
    index_dir: Path
    db_path: Path
    is_active: bool


def _to_resolved(record: DatasetRecord) -> ResolvedDataset:
    return ResolvedDataset(
        key=record.key,
        title=record.title,
        domain_type=record.domain_type,
        profile_key=record.profile_key,
        source_dir=resolve_project_path(record.source_dir),
        index_dir=resolve_project_path(record.index_dir),
        db_path=resolve_project_path(record.db_path),
        is_active=record.is_active,
    )


def resolve_dataset(session: Session, dataset_key: str | None = None) -> ResolvedDataset:
    record = get_dataset_record(session, dataset_key) if dataset_key else get_active_dataset_record(session)
    if record is None:
        missing_key = dataset_key or "<active>"
        raise DatasetNotFoundError(missing_key)
    return _to_resolved(record)
