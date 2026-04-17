from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.config import get_project_root, get_settings
from api.models import (
    FTDatasetRecord,
    FTDatasetRowRecord,
    FTDatasetVersionRecord,
    FTModelArtifactRecord,
    FTTrainingJobRecord,
    ModelRegistryRecord,
)
from api.services.jobs import create_job

ALLOWED_TRAINING_STATUSES = {"queued", "running", "succeeded", "failed"}


def _next_prefixed_id(session: Session, model: type, prefix: str) -> str:
    next_value = 1
    for existing_id in session.scalars(select(model.id)).all():
        suffix = str(existing_id).replace(f"{prefix}-", "", 1)
        if suffix.isdigit():
            next_value = max(next_value, int(suffix) + 1)
    return f"{prefix}-{next_value}"


def _artifacts_root() -> Path:
    return get_project_root() / "data" / "model_artifacts"


def _serialize_artifact(
    artifact: FTModelArtifactRecord | None,
) -> dict[str, Any] | None:
    if artifact is None:
        return None
    return {
        "id": artifact.id,
        "training_job_id": artifact.training_job_id,
        "artifact_type": artifact.artifact_type,
        "local_path": artifact.local_path,
        "metadata_json": artifact.metadata_json,
        "created_at": artifact.created_at.isoformat()
        if artifact.created_at is not None
        else None,
    }


def _serialize_model(
    model: ModelRegistryRecord, artifact: FTModelArtifactRecord | None
) -> dict[str, Any]:
    serving_model_name = (
        model.base_model_name
        if model.source_type == "fine_tuned"
        else model.ollama_model_name
    )
    return {
        "id": model.id,
        "display_name": model.display_name,
        "source_type": model.source_type,
        "base_model_name": model.base_model_name,
        "ollama_model_name": model.ollama_model_name,
        "serving_model_name": serving_model_name,
        "artifact_id": model.artifact_id,
        "status": model.status,
        "tags_json": model.tags_json,
        "description": model.description,
        "created_at": model.created_at.isoformat()
        if model.created_at is not None
        else None,
        "updated_at": model.updated_at.isoformat()
        if model.updated_at is not None
        else None,
        "artifact": _serialize_artifact(artifact),
    }


def _serialize_training_job(
    training_job: FTTrainingJobRecord,
    dataset: FTDatasetRecord | None,
    dataset_version: FTDatasetVersionRecord | None,
    artifacts: list[FTModelArtifactRecord],
    models: list[ModelRegistryRecord],
) -> dict[str, Any]:
    return {
        "id": training_job.id,
        "dataset_version_id": training_job.dataset_version_id,
        "dataset_id": dataset.id if dataset is not None else None,
        "dataset_name": dataset.name if dataset is not None else None,
        "dataset_version_label": dataset_version.version_label
        if dataset_version is not None
        else None,
        "base_model_name": training_job.base_model_name,
        "training_method": training_job.training_method,
        "hyperparams_json": training_job.hyperparams_json,
        "status": training_job.status,
        "backing_job_id": training_job.backing_job_id,
        "log_text": training_job.log_text,
        "created_at": training_job.created_at.isoformat()
        if training_job.created_at is not None
        else None,
        "started_at": training_job.started_at.isoformat()
        if training_job.started_at is not None
        else None,
        "finished_at": training_job.finished_at.isoformat()
        if training_job.finished_at is not None
        else None,
        "artifacts": [_serialize_artifact(item) for item in artifacts],
        "registered_models": [
            _serialize_model(
                model,
                next(
                    (
                        artifact
                        for artifact in artifacts
                        if artifact.id == model.artifact_id
                    ),
                    None,
                ),
            )
            for model in models
        ],
    }


def ensure_default_models(session: Session) -> list[dict[str, Any]]:
    settings = get_settings()
    defaults = [
        {
            "display_name": "Default Ollama model",
            "base_model_name": settings.ollama_model,
            "ollama_model_name": settings.ollama_model,
            "status": "active",
            "description": "Default serving model configured for workflow and inference requests.",
            "tags_json": ["base", "default"],
        }
    ]
    if (
        settings.ollama_fallback_model
        and settings.ollama_fallback_model != settings.ollama_model
    ):
        defaults.append(
            {
                "display_name": "Fallback Ollama model",
                "base_model_name": settings.ollama_fallback_model,
                "ollama_model_name": settings.ollama_fallback_model,
                "status": "registered",
                "description": "Fallback serving model used when the default Ollama model is unavailable.",
                "tags_json": ["base", "fallback"],
            }
        )

    now = datetime.now(timezone.utc)
    for item in defaults:
        existing = session.scalar(
            select(ModelRegistryRecord).where(
                ModelRegistryRecord.ollama_model_name == item["ollama_model_name"]
            )
        )
        if existing is not None:
            existing.display_name = item["display_name"]
            existing.base_model_name = item["base_model_name"]
            existing.source_type = "base"
            existing.status = item["status"]
            existing.tags_json = item["tags_json"]
            existing.description = item["description"]
            existing.updated_at = now
            continue
        session.add(
            ModelRegistryRecord(
                id=_next_prefixed_id(session, ModelRegistryRecord, "model"),
                display_name=item["display_name"],
                source_type="base",
                base_model_name=item["base_model_name"],
                ollama_model_name=item["ollama_model_name"],
                status=item["status"],
                tags_json=item["tags_json"],
                description=item["description"],
                updated_at=now,
            )
        )

    session.commit()
    models = session.scalars(
        select(ModelRegistryRecord).order_by(
            ModelRegistryRecord.created_at.desc(), ModelRegistryRecord.id.desc()
        )
    ).all()
    return [_serialize_model(model, None) for model in models]


def list_models(session: Session) -> list[dict[str, Any]]:
    models = session.scalars(
        select(ModelRegistryRecord).order_by(
            ModelRegistryRecord.created_at.desc(), ModelRegistryRecord.id.desc()
        )
    ).all()
    artifact_ids = [
        model.artifact_id for model in models if model.artifact_id is not None
    ]
    artifacts = (
        {
            artifact.id: artifact
            for artifact in session.scalars(
                select(FTModelArtifactRecord).where(
                    FTModelArtifactRecord.id.in_(artifact_ids)
                )
            ).all()
        }
        if artifact_ids
        else {}
    )
    return [
        _serialize_model(model, artifacts.get(model.artifact_id)) for model in models
    ]


def get_model(session: Session, model_id: str) -> dict[str, Any] | None:
    model = session.get(ModelRegistryRecord, model_id)
    if model is None:
        return None
    artifact = (
        session.get(FTModelArtifactRecord, model.artifact_id)
        if model.artifact_id
        else None
    )
    return _serialize_model(model, artifact)


def create_training_job(
    session: Session,
    *,
    dataset_version_id: str,
    base_model_name: str,
    training_method: str,
    hyperparams_json: dict[str, Any] | None,
) -> dict[str, Any]:
    dataset_version = session.get(FTDatasetVersionRecord, dataset_version_id)
    if dataset_version is None:
        raise KeyError(dataset_version_id)
    if dataset_version.status == "draft":
        raise ValueError("dataset version must be validated or locked before training")
    dataset = session.get(FTDatasetRecord, dataset_version.dataset_id)
    assert dataset is not None
    training_job = FTTrainingJobRecord(
        id=_next_prefixed_id(session, FTTrainingJobRecord, "ft-job"),
        dataset_version_id=dataset_version_id,
        base_model_name=base_model_name.strip(),
        training_method=training_method.strip() or "stub_adapter",
        hyperparams_json=hyperparams_json or {},
    )
    session.add(training_job)
    session.flush()
    queue_job = create_job(
        session,
        job_type="ft_train_model",
        payload_json={
            "training_job_id": training_job.id,
            "dataset_version_id": dataset_version_id,
            "base_model_name": training_job.base_model_name,
            "training_method": training_job.training_method,
        },
        max_attempts=2,
        commit=False,
    )
    training_job.backing_job_id = queue_job.id
    training_job.log_text = "Queued lightweight training scaffold."
    session.commit()
    return get_training_job(session, training_job.id) or {"id": training_job.id}


def list_training_jobs(session: Session) -> list[dict[str, Any]]:
    jobs = session.scalars(
        select(FTTrainingJobRecord).order_by(
            FTTrainingJobRecord.created_at.desc(), FTTrainingJobRecord.id.desc()
        )
    ).all()
    version_ids = [job.dataset_version_id for job in jobs]
    dataset_versions = (
        {
            item.id: item
            for item in session.scalars(
                select(FTDatasetVersionRecord).where(
                    FTDatasetVersionRecord.id.in_(version_ids)
                )
            ).all()
        }
        if version_ids
        else {}
    )
    dataset_ids = [item.dataset_id for item in dataset_versions.values()]
    datasets = (
        {
            item.id: item
            for item in session.scalars(
                select(FTDatasetRecord).where(FTDatasetRecord.id.in_(dataset_ids))
            ).all()
        }
        if dataset_ids
        else {}
    )
    artifacts = session.scalars(select(FTModelArtifactRecord)).all()
    models = session.scalars(select(ModelRegistryRecord)).all()
    artifacts_by_job: dict[str, list[FTModelArtifactRecord]] = {}
    for artifact in artifacts:
        artifacts_by_job.setdefault(artifact.training_job_id, []).append(artifact)
    models_by_job: dict[str, list[ModelRegistryRecord]] = {}
    artifact_to_job = {artifact.id: artifact.training_job_id for artifact in artifacts}
    for model in models:
        if model.artifact_id is None:
            continue
        training_job_id = artifact_to_job.get(model.artifact_id)
        if training_job_id is not None:
            models_by_job.setdefault(training_job_id, []).append(model)
    return [
        _serialize_training_job(
            job,
            datasets.get(dataset_versions[job.dataset_version_id].dataset_id)
            if job.dataset_version_id in dataset_versions
            else None,
            dataset_versions.get(job.dataset_version_id),
            artifacts_by_job.get(job.id, []),
            models_by_job.get(job.id, []),
        )
        for job in jobs
    ]


def get_training_job(session: Session, training_job_id: str) -> dict[str, Any] | None:
    training_job = session.get(FTTrainingJobRecord, training_job_id)
    if training_job is None:
        return None
    dataset_version = session.get(
        FTDatasetVersionRecord, training_job.dataset_version_id
    )
    dataset = (
        session.get(FTDatasetRecord, dataset_version.dataset_id)
        if dataset_version
        else None
    )
    artifacts = session.scalars(
        select(FTModelArtifactRecord).where(
            FTModelArtifactRecord.training_job_id == training_job_id
        )
    ).all()
    models = (
        session.scalars(
            select(ModelRegistryRecord).where(
                ModelRegistryRecord.artifact_id.in_(
                    [artifact.id for artifact in artifacts]
                )
            )
        ).all()
        if artifacts
        else []
    )
    return _serialize_training_job(
        training_job, dataset, dataset_version, artifacts, models
    )


def resolve_model_selection(
    session: Session,
    *,
    model_id: str | None = None,
    ollama_model_name: str | None = None,
) -> dict[str, Any]:
    ensure_default_models(session)
    if model_id and ollama_model_name:
        raise ValueError("provide either model_id or ollama_model_name, not both")
    if model_id:
        model = session.get(ModelRegistryRecord, model_id)
        if model is None:
            raise KeyError(model_id)
        artifact = (
            session.get(FTModelArtifactRecord, model.artifact_id)
            if model.artifact_id
            else None
        )
        return _serialize_model(model, artifact)
    if ollama_model_name:
        model = session.scalar(
            select(ModelRegistryRecord).where(
                ModelRegistryRecord.ollama_model_name == ollama_model_name
            )
        )
        if model is not None:
            artifact = (
                session.get(FTModelArtifactRecord, model.artifact_id)
                if model.artifact_id
                else None
            )
            return _serialize_model(model, artifact)
        return {
            "id": None,
            "display_name": ollama_model_name,
            "source_type": "direct",
            "base_model_name": ollama_model_name,
            "ollama_model_name": ollama_model_name,
            "artifact_id": None,
            "status": "direct",
            "tags_json": ["direct"],
            "description": "Direct Ollama model selection outside the registry.",
            "created_at": None,
            "updated_at": None,
            "artifact": None,
        }
    active = session.scalar(
        select(ModelRegistryRecord)
        .where(ModelRegistryRecord.status.in_(["active", "registered"]))
        .order_by(
            ModelRegistryRecord.status.asc(), ModelRegistryRecord.created_at.asc()
        )
        .limit(1)
    )
    if active is None:
        raise LookupError("no registered models available")
    artifact = (
        session.get(FTModelArtifactRecord, active.artifact_id)
        if active.artifact_id
        else None
    )
    return _serialize_model(active, artifact)


def complete_training_job(
    session: Session,
    *,
    training_job_id: str,
    artifact_type: str = "placeholder",
    status: str = "succeeded",
) -> dict[str, Any]:
    if status not in ALLOWED_TRAINING_STATUSES:
        raise ValueError("unsupported training status")
    training_job = session.get(FTTrainingJobRecord, training_job_id)
    if training_job is None:
        raise KeyError(training_job_id)
    dataset_version = session.get(
        FTDatasetVersionRecord, training_job.dataset_version_id
    )
    dataset = (
        session.get(FTDatasetRecord, dataset_version.dataset_id)
        if dataset_version
        else None
    )
    if dataset is None or dataset_version is None:
        raise RuntimeError("training job is missing dataset metadata")

    rows = session.scalars(
        select(FTDatasetRowRecord).where(
            FTDatasetRowRecord.dataset_version_id == training_job.dataset_version_id
        )
    ).all()
    if not rows:
        raise RuntimeError("training dataset version has no rows")
    invalid_rows = [row for row in rows if row.validation_status != "valid"]
    if invalid_rows:
        raise RuntimeError("training dataset version contains invalid rows")

    now = datetime.now(timezone.utc)
    training_job.status = status
    training_job.started_at = training_job.started_at or now
    training_job.finished_at = now

    artifact_dir = _artifacts_root() / training_job.id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = artifact_dir / "artifact.json"
    manifest_payload = {
        "training_job_id": training_job.id,
        "dataset_id": dataset.id,
        "dataset_version_id": dataset_version.id,
        "dataset_version_label": dataset_version.version_label,
        "base_model_name": training_job.base_model_name,
        "training_method": training_job.training_method,
        "artifact_type": artifact_type,
        "row_count": len(rows),
        "status": status,
        "generated_at": now.isoformat(),
        "note": "Lightweight training scaffold artifact. Replace this manifest with a real trainer output later.",
    }
    manifest_path.write_text(json.dumps(manifest_payload, indent=2), encoding="utf-8")

    artifact = FTModelArtifactRecord(
        id=_next_prefixed_id(session, FTModelArtifactRecord, "artifact"),
        training_job_id=training_job.id,
        artifact_type=artifact_type,
        local_path=str(manifest_path),
        metadata_json=manifest_payload,
    )
    session.add(artifact)
    session.flush()

    registry_entry = ModelRegistryRecord(
        id=_next_prefixed_id(session, ModelRegistryRecord, "model"),
        display_name=f"{dataset.name} {dataset_version.version_label}",
        source_type="fine_tuned",
        base_model_name=training_job.base_model_name,
        ollama_model_name=f"placeholder::{training_job.id}",
        artifact_id=artifact.id,
        status="registered",
        tags_json=["fine_tuned", dataset.task_type, training_job.training_method],
        description=(
            f"Stub fine-tuned registry entry for {dataset.name} {dataset_version.version_label}. "
            "Inference currently routes to the base serving model until a real artifact import step is added."
        ),
        updated_at=now,
    )
    session.add(registry_entry)
    training_job.log_text = (
        f"Prepared {artifact_type} artifact scaffold at {manifest_path}. "
        "Registered a reviewable model entry for inference selection."
    )
    session.commit()
    return get_training_job(session, training_job.id) or {"id": training_job.id}
