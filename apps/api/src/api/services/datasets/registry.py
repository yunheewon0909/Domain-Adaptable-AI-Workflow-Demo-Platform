from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.config import get_settings
from api.models import DatasetRecord


@dataclass(frozen=True)
class DatasetDefinition:
    key: str
    title: str
    domain_type: str
    profile_key: str
    source_dir: str
    index_dir: str
    db_path: str
    is_active: bool = False


def _default_dataset_definitions() -> list[DatasetDefinition]:
    settings = get_settings()
    return [
        DatasetDefinition(
            key="industrial_demo",
            title="Industrial Operations Demo",
            domain_type="industrial_ops",
            profile_key="industrial_ops",
            source_dir=settings.rag_source_dir,
            index_dir=settings.rag_index_dir,
            db_path=settings.rag_db_path,
            is_active=True,
        ),
        DatasetDefinition(
            key="enterprise_docs",
            title="Enterprise Knowledge Demo",
            domain_type="enterprise_docs",
            profile_key="enterprise_docs",
            source_dir="data/datasets/enterprise_docs/source",
            index_dir="data/datasets/enterprise_docs/index",
            db_path="data/datasets/enterprise_docs/index/rag.db",
            is_active=False,
        ),
    ]


def _apply_definition(record: DatasetRecord, definition: DatasetDefinition) -> None:
    record.title = definition.title
    record.domain_type = definition.domain_type
    record.profile_key = definition.profile_key
    record.source_dir = definition.source_dir
    record.index_dir = definition.index_dir
    record.db_path = definition.db_path


def ensure_default_datasets(session: Session) -> list[DatasetRecord]:
    definitions = _default_dataset_definitions()
    existing = {
        record.key: record
        for record in session.scalars(select(DatasetRecord)).all()
    }

    now = datetime.now(timezone.utc)
    for definition in definitions:
        record = existing.get(definition.key)
        if record is None:
            record = DatasetRecord(
                key=definition.key,
                title=definition.title,
                domain_type=definition.domain_type,
                profile_key=definition.profile_key,
                source_dir=definition.source_dir,
                index_dir=definition.index_dir,
                db_path=definition.db_path,
                is_active=definition.is_active,
                updated_at=now,
            )
            session.add(record)
            existing[definition.key] = record
            continue

        _apply_definition(record, definition)
        record.updated_at = now

    session.flush()

    active_records = [record for record in existing.values() if record.is_active]
    if not active_records and definitions:
        existing[definitions[0].key].is_active = True
        existing[definitions[0].key].updated_at = now
    elif len(active_records) > 1:
        keep_key = next((definition.key for definition in definitions if definition.is_active), active_records[0].key)
        for record in active_records:
            record.is_active = record.key == keep_key
            record.updated_at = now

    session.commit()
    return list_dataset_records(session, ensure_seeded=False)


def list_dataset_records(session: Session, *, ensure_seeded: bool = True) -> list[DatasetRecord]:
    if ensure_seeded:
        ensure_default_datasets(session)
    return list(
        session.scalars(
            select(DatasetRecord).order_by(
                DatasetRecord.is_active.desc(),
                DatasetRecord.created_at.asc(),
                DatasetRecord.key.asc(),
            )
        ).all()
    )


def get_dataset_record(session: Session, dataset_key: str, *, ensure_seeded: bool = True) -> DatasetRecord | None:
    if ensure_seeded:
        ensure_default_datasets(session)
    return session.get(DatasetRecord, dataset_key)


def get_active_dataset_record(session: Session, *, ensure_seeded: bool = True) -> DatasetRecord | None:
    if ensure_seeded:
        ensure_default_datasets(session)
    return session.scalar(
        select(DatasetRecord)
        .where(DatasetRecord.is_active.is_(True))
        .order_by(DatasetRecord.updated_at.desc(), DatasetRecord.key.asc())
        .limit(1)
    )


def set_active_dataset(session: Session, dataset_key: str) -> DatasetRecord:
    records = list_dataset_records(session)
    target = next((record for record in records if record.key == dataset_key), None)
    if target is None:
        raise KeyError(dataset_key)

    now = datetime.now(timezone.utc)
    for record in records:
        record.is_active = record.key == dataset_key
        record.updated_at = now

    session.commit()
    session.refresh(target)
    return target


def dataset_to_dict(record: DatasetRecord) -> dict[str, object]:
    return {
        "key": record.key,
        "title": record.title,
        "domain_type": record.domain_type,
        "profile_key": record.profile_key,
        "source_dir": record.source_dir,
        "index_dir": record.index_dir,
        "db_path": record.db_path,
        "is_active": record.is_active,
    }
