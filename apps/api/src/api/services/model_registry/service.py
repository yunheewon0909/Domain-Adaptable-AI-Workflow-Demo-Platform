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
from api.services.fine_tuning.artifacts import (
    build_publish_manifest,
    validate_publish_artifacts,
    validate_training_artifacts,
)
from api.services.fine_tuning.dataset_formatters import (
    export_dataset_version_for_training,
)
from api.services.fine_tuning.trainer import run_training_backend

BASE_MODEL_READY_STATUSES = {"active", "registered"}
ALLOWED_TRAINING_STATUSES = {
    "queued",
    "preparing_data",
    "training",
    "packaging",
    "registering",
    "running",
    "succeeded",
    "failed",
}
ARTIFACT_ONLY_MODEL_STATUSES = {"artifact_ready"}
READY_MODEL_STATUSES = {"published"}
ALLOWED_PUBLISH_STATUSES = {"not_requested", "publish_ready", "published", "failed"}


def _next_prefixed_id(session: Session, model: type, prefix: str) -> str:
    next_value = 1
    for existing_id in session.scalars(select(model.id)).all():
        suffix = str(existing_id).replace(f"{prefix}-", "", 1)
        if suffix.isdigit():
            next_value = max(next_value, int(suffix) + 1)
    return f"{prefix}-{next_value}"


def _artifacts_root() -> Path:
    settings = get_settings()
    return Path(settings.training_artifact_dir)


def _serialize_readiness(model: ModelRegistryRecord) -> dict[str, Any]:
    selectable = False
    selectable_reason = "model is not selectable"
    runtime_ready = False
    runtime_ready_reason = "runtime readiness is not available"
    if model.source_type == "base":
        selectable = model.status in BASE_MODEL_READY_STATUSES
        selectable_reason = (
            "base model is registered for direct inference"
            if selectable
            else "base model is not in a ready status"
        )
        runtime_ready = selectable
        runtime_ready_reason = selectable_reason
    elif model.source_type == "fine_tuned":
        selectable = (
            model.status in READY_MODEL_STATUSES
            and model.publish_status == "published"
            and bool(model.published_model_name)
        )
        runtime_ready = selectable
        if selectable:
            selectable_reason = "fine-tuned model has a published serving target"
            runtime_ready_reason = selectable_reason
        elif model.publish_status == "publish_ready":
            selectable_reason = "PEFT adapter exists and the publish manifest is ready, but no Ollama serving model has been created yet."
            runtime_ready_reason = "Automatic Ollama import is not implemented, so this fine-tuned model remains artifact-only until a real serving model exists."
        elif model.publish_status == "failed":
            selectable_reason = "fine-tuned model publish preparation failed"
            runtime_ready_reason = (
                "publish preparation failed before a serving model became available"
            )
        else:
            selectable_reason = (
                "fine-tuned model is artifact-ready only and not yet serving-ready"
            )
            runtime_ready_reason = selectable_reason
    return {
        "selectable": selectable,
        "selectable_reason": selectable_reason,
        "publish_status": model.publish_status,
        "runtime_ready": runtime_ready,
        "runtime_ready_reason": runtime_ready_reason,
    }


def _artifact_metadata_value(artifact: FTModelArtifactRecord | None, key: str) -> Any:
    if artifact is None:
        return None
    return dict(artifact.metadata_json or {}).get(key)


def _lineage_value(model: ModelRegistryRecord, key: str) -> Any:
    return dict(model.lineage_json or {}).get(key)


def _lineage_warning(
    *, base_model_name: str | None, trainer_model_name: str | None
) -> str | None:
    if not base_model_name or not trainer_model_name:
        return None
    if base_model_name == trainer_model_name:
        return None
    return "Serving lineage and trainer source differ. This is acceptable for smoke tests but does not mean the serving model itself was fine-tuned."


def _model_warnings(
    model: ModelRegistryRecord, artifact: FTModelArtifactRecord | None
) -> list[str]:
    warnings: list[str] = []
    if model.source_type == "fine_tuned":
        warnings.append(
            "This registry entry tracks a PEFT adapter artifact. It is not itself an Ollama serving model."
        )
        if model.publish_status == "publish_ready":
            warnings.append(
                "Publish-ready means a manifest/template exists. Automatic Ollama import is not implemented by this repository."
            )
    validation = _artifact_metadata_value(artifact, "validation")
    if isinstance(validation, dict):
        warnings.extend(str(item) for item in validation.get("warnings") or [])
    mismatch_warning = _lineage_warning(
        base_model_name=model.base_model_name,
        trainer_model_name=_lineage_value(model, "trainer_model_name"),
    )
    if mismatch_warning:
        warnings.append(mismatch_warning)
    deduped: list[str] = []
    for item in warnings:
        if item and item not in deduped:
            deduped.append(item)
    return deduped


def _artifact_paths_by_type(
    artifacts: list[FTModelArtifactRecord],
) -> dict[str, str | None]:
    by_type = {artifact.artifact_type: artifact.local_path for artifact in artifacts}
    publish_artifact = next(
        (
            artifact
            for artifact in artifacts
            if artifact.artifact_type == "publish_manifest"
        ),
        None,
    )
    publish_metadata = (
        dict(publish_artifact.metadata_json or {})
        if publish_artifact is not None
        else {}
    )
    return {
        "dataset_export_dir": by_type.get("dataset_export"),
        "adapter_dir": by_type.get("adapter_bundle"),
        "training_report_path": by_type.get("training_report"),
        "merged_model_dir": by_type.get("merged_model"),
        "publish_manifest_path": by_type.get("publish_manifest"),
        "modelfile_template_path": publish_metadata.get("modelfile_template_path"),
        "training_log_path": next(
            (
                dict(artifact.metadata_json or {}).get("log_path")
                for artifact in artifacts
                if artifact.artifact_type == "training_report"
            ),
            None,
        ),
    }


def _resolve_training_job_trainer_model_name(
    training_job: FTTrainingJobRecord,
    artifacts: list[FTModelArtifactRecord],
    models: list[ModelRegistryRecord],
) -> str | None:
    explicit = str(
        training_job.hyperparams_json.get("trainer_model_name") or ""
    ).strip()
    if explicit:
        return explicit
    for artifact in artifacts:
        metadata = dict(artifact.metadata_json or {})
        trainer_model_name = str(metadata.get("trainer_model_name") or "").strip()
        if trainer_model_name:
            return trainer_model_name
    for model in models:
        trainer_model_name = str(
            _lineage_value(model, "trainer_model_name") or ""
        ).strip()
        if trainer_model_name:
            return trainer_model_name
    return None


def _resolve_training_job_publish_readiness(
    models: list[ModelRegistryRecord],
) -> dict[str, Any] | None:
    if not models:
        return None
    model = models[0]
    readiness = _serialize_readiness(model)
    return {
        "status": model.status,
        "publish_status": model.publish_status,
        "serving_model_name": model.published_model_name,
        "candidate_published_model_name": _lineage_value(
            model, "candidate_published_model_name"
        ),
        "selectable": readiness["selectable"],
        "selectable_reason": readiness["selectable_reason"],
        "runtime_ready": readiness["runtime_ready"],
        "runtime_ready_reason": readiness["runtime_ready_reason"],
        "warnings": _model_warnings(model, None),
    }


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
    serving_model_name = model.ollama_model_name
    if model.source_type == "fine_tuned":
        serving_model_name = model.published_model_name
    readiness = _serialize_readiness(model)
    artifact_metadata = (
        dict(artifact.metadata_json or {}) if artifact is not None else {}
    )
    return {
        "id": model.id,
        "display_name": model.display_name,
        "source_type": model.source_type,
        "base_model_name": model.base_model_name,
        "trainer_model_name": _lineage_value(model, "trainer_model_name"),
        "trainer_backend": artifact_metadata.get("trainer_backend")
        or _lineage_value(model, "trainer_backend"),
        "ollama_model_name": model.ollama_model_name,
        "published_model_name": model.published_model_name,
        "candidate_published_model_name": _lineage_value(
            model, "candidate_published_model_name"
        ),
        "serving_model_name": serving_model_name,
        "artifact_id": model.artifact_id,
        "artifact_type": artifact.artifact_type if artifact is not None else None,
        "artifact_format": artifact_metadata.get("artifact_format"),
        "artifact_valid": artifact_metadata.get("artifact_valid"),
        "status": model.status,
        "publish_status": model.publish_status,
        "tags_json": model.tags_json,
        "lineage_json": model.lineage_json,
        "description": model.description,
        "created_at": model.created_at.isoformat()
        if model.created_at is not None
        else None,
        "updated_at": model.updated_at.isoformat()
        if model.updated_at is not None
        else None,
        "artifact": _serialize_artifact(artifact),
        "readiness": readiness,
        "warnings": _model_warnings(model, artifact),
    }


def _serialize_training_job(
    training_job: FTTrainingJobRecord,
    dataset: FTDatasetRecord | None,
    dataset_version: FTDatasetVersionRecord | None,
    artifacts: list[FTModelArtifactRecord],
    models: list[ModelRegistryRecord],
) -> dict[str, Any]:
    trainer_model_name = _resolve_training_job_trainer_model_name(
        training_job, artifacts, models
    )
    artifact_paths = _artifact_paths_by_type(artifacts)
    report_artifact = next(
        (
            artifact
            for artifact in artifacts
            if artifact.artifact_type == "training_report"
        ),
        None,
    )
    adapter_artifact = next(
        (
            artifact
            for artifact in artifacts
            if artifact.artifact_type == "adapter_bundle"
        ),
        None,
    )
    artifact_validation = _artifact_metadata_value(adapter_artifact, "validation")
    lineage_warning = _lineage_warning(
        base_model_name=training_job.base_model_name,
        trainer_model_name=trainer_model_name,
    )
    return {
        "id": training_job.id,
        "dataset_version_id": training_job.dataset_version_id,
        "dataset_id": dataset.id if dataset is not None else None,
        "dataset_name": dataset.name if dataset is not None else None,
        "dataset_version_label": dataset_version.version_label
        if dataset_version is not None
        else None,
        "base_model_name": training_job.base_model_name,
        "trainer_model_name": trainer_model_name,
        "training_method": training_job.training_method,
        "hyperparams_json": training_job.hyperparams_json,
        "status": training_job.status,
        "trainer_backend": training_job.trainer_backend,
        "device": _artifact_metadata_value(report_artifact, "device"),
        "backing_job_id": training_job.backing_job_id,
        "train_rows": training_job.train_rows,
        "val_rows": training_job.val_rows,
        "test_rows": training_job.test_rows,
        "format_summary_json": training_job.format_summary_json,
        "metrics_json": training_job.metrics_json,
        "evaluation_json": training_job.evaluation_json,
        "error_json": training_job.error_json,
        "output_dir": training_job.output_dir,
        "artifact_paths": artifact_paths,
        "artifact_validation": artifact_validation,
        "lineage_warning": lineage_warning,
        "publish_readiness": _resolve_training_job_publish_readiness(models),
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
            existing.publish_status = "published"
            existing.published_model_name = item["ollama_model_name"]
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
                published_model_name=item["ollama_model_name"],
                status=item["status"],
                publish_status="published",
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
        _serialize_model(
            model,
            artifacts.get(model.artifact_id) if model.artifact_id is not None else None,
        )
        for model in models
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
    resolved_training_method = (
        training_method.strip() or get_settings().ft_default_training_method
    )
    if resolved_training_method == "sft_lora" and dataset_version.status != "locked":
        raise ValueError("real sft_lora training requires a locked dataset version")
    training_job = FTTrainingJobRecord(
        id=_next_prefixed_id(session, FTTrainingJobRecord, "ft-job"),
        dataset_version_id=dataset_version_id,
        base_model_name=base_model_name.strip(),
        training_method=resolved_training_method,
        hyperparams_json=hyperparams_json or {},
        trainer_backend=get_settings().ft_trainer_backend,
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
    training_job.log_text = (
        "Queued fine-tuning job. "
        "Real trainer execution requires a locked dataset version and compatible local training dependencies."
    )
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
        training_job, dataset, dataset_version, list(artifacts), list(models)
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
        readiness = _serialize_readiness(model)
        if not readiness["selectable"]:
            raise LookupError(str(readiness["selectable_reason"]))
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
            readiness = _serialize_readiness(model)
            if not readiness["selectable"]:
                raise LookupError(str(readiness["selectable_reason"]))
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
    artifact_type: str = "adapter_bundle",
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

    failure_phase = "preparing_data"
    now = datetime.now(timezone.utc)
    try:
        training_job.status = "preparing_data"
        training_job.started_at = training_job.started_at or now

        artifact_dir = _artifacts_root() / training_job.id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        export_dir = artifact_dir / "dataset_export"
        export_result = export_dataset_version_for_training(
            dataset,
            dataset_version,
            list(rows),
            export_root=export_dir,
            require_locked=training_job.training_method == "sft_lora",
        )
        training_job.train_rows = export_result.row_counts.get("train")
        training_job.val_rows = export_result.row_counts.get("val")
        training_job.test_rows = export_result.row_counts.get("test")
        training_job.format_summary_json = export_result.format_summary
        training_job.output_dir = str(artifact_dir)
        training_job.status = "training"
        failure_phase = "training"
        session.flush()

        settings = get_settings()
        training_output = run_training_backend(
            export_result,
            base_model_name=training_job.base_model_name,
            training_method=training_job.training_method,
            hyperparams_json=training_job.hyperparams_json,
            settings=settings,
            output_dir=artifact_dir / "trainer_output",
        )

        training_job.status = "packaging"
        failure_phase = "packaging"
        training_job.trainer_backend = training_output.trainer_backend
        training_job.metrics_json = training_output.metrics
        training_job.evaluation_json = training_output.evaluation
        artifact_validation = validate_training_artifacts(
            training_artifacts=training_output,
            base_model_name=training_job.base_model_name,
            smoke_test=bool(training_job.hyperparams_json.get("smoke_test", False)),
        )
        if not artifact_validation["artifact_valid"]:
            raise RuntimeError(
                "training artifacts failed validation: "
                + ", ".join(artifact_validation["missing"])
            )
        training_job.log_text = (
            f"Exported dataset to {export_result.export_dir}. "
            f"Validated PEFT adapter artifact at {training_output.adapter_dir}."
        )

        dataset_export_artifact = FTModelArtifactRecord(
            id=_next_prefixed_id(session, FTModelArtifactRecord, "artifact"),
            training_job_id=training_job.id,
            artifact_type="dataset_export",
            local_path=export_result.export_dir,
            metadata_json={
                **export_result.format_summary,
                "train_file": export_result.train_file,
                "val_file": export_result.val_file,
                "test_file": export_result.test_file,
                "all_rows_file": export_result.all_rows_file,
                "summary_file": export_result.summary_file,
            },
        )
        session.add(dataset_export_artifact)
        session.flush()

        adapter_artifact = FTModelArtifactRecord(
            id=_next_prefixed_id(session, FTModelArtifactRecord, "artifact"),
            training_job_id=training_job.id,
            artifact_type=artifact_type,
            local_path=training_output.adapter_dir,
            metadata_json={
                "training_job_id": training_job.id,
                "dataset_version_id": dataset_version.id,
                "base_model_name": training_job.base_model_name,
                "trainer_model_name": training_output.trainer_model_name,
                "trainer_backend": training_output.trainer_backend,
                "artifact_format": "peft_adapter",
                "artifact_valid": artifact_validation["artifact_valid"],
                "status": "ready",
                "device": training_output.device,
                "smoke_test": artifact_validation["smoke_test"],
                "created_at": now.isoformat(),
                "metrics": training_output.metrics,
                "validation": artifact_validation,
            },
        )
        session.add(adapter_artifact)
        session.flush()

        report_artifact = FTModelArtifactRecord(
            id=_next_prefixed_id(session, FTModelArtifactRecord, "artifact"),
            training_job_id=training_job.id,
            artifact_type="training_report",
            local_path=training_output.report_path,
            metadata_json={
                "log_path": training_output.logs_path,
                "device": training_output.device,
                "evaluation": training_output.evaluation,
                "metrics": training_output.metrics,
                "artifact_valid": artifact_validation["artifact_valid"],
            },
        )
        session.add(report_artifact)
        session.flush()

        if training_output.merged_model_dir is not None:
            merged_artifact = FTModelArtifactRecord(
                id=_next_prefixed_id(session, FTModelArtifactRecord, "artifact"),
                training_job_id=training_job.id,
                artifact_type="merged_model",
                local_path=training_output.merged_model_dir,
                metadata_json={
                    "status": "ready",
                    "artifact_format": "transformers_pretrained",
                    "base_model_name": training_job.base_model_name,
                },
            )
            session.add(merged_artifact)
            session.flush()

        publish_manifest_path, publish_manifest = build_publish_manifest(
            manifest_dir=artifact_dir / "publish",
            dataset_export=export_result,
            training_artifacts=training_output,
            base_model_name=training_job.base_model_name,
            trainer_model_name=training_output.trainer_model_name,
            settings=settings,
        )
        publish_validation = validate_publish_artifacts(
            manifest_path=publish_manifest_path,
            modelfile_template_path=Path(
                str(publish_manifest.get("modelfile_template_path") or "")
            ),
            manifest_payload=publish_manifest,
            training_validation=artifact_validation,
        )
        if not publish_validation["artifact_valid"]:
            raise RuntimeError(
                "publish artifacts failed validation: "
                + ", ".join(publish_validation["missing"])
            )
        publish_artifact = FTModelArtifactRecord(
            id=_next_prefixed_id(session, FTModelArtifactRecord, "artifact"),
            training_job_id=training_job.id,
            artifact_type="publish_manifest",
            local_path=str(publish_manifest_path),
            metadata_json={
                **publish_manifest,
                "artifact_valid": publish_validation["artifact_valid"],
                "validation": publish_validation,
            },
        )
        session.add(publish_artifact)
        session.flush()

        training_job.status = "registering"
        failure_phase = "registering"
        registry_entry = ModelRegistryRecord(
            id=_next_prefixed_id(session, ModelRegistryRecord, "model"),
            display_name=f"{dataset.name} {dataset_version.version_label}",
            source_type="fine_tuned",
            base_model_name=training_job.base_model_name,
            ollama_model_name=f"artifact::{training_job.id}",
            published_model_name=None,
            artifact_id=adapter_artifact.id,
            status="artifact_ready",
            publish_status="publish_ready",
            tags_json=["fine_tuned", dataset.task_type, training_job.training_method],
            lineage_json={
                "dataset_id": dataset.id,
                "dataset_version_id": dataset_version.id,
                "dataset_version_label": dataset_version.version_label,
                "trainer_model_name": training_output.trainer_model_name,
                "trainer_backend": training_output.trainer_backend,
                "artifact_type": artifact_type,
                "artifact_format": "peft_adapter",
                "training_job_id": training_job.id,
                "candidate_published_model_name": publish_manifest.get(
                    "candidate_model_name"
                ),
                "lineage_warning": _lineage_warning(
                    base_model_name=training_job.base_model_name,
                    trainer_model_name=training_output.trainer_model_name,
                ),
            },
            description=(
                f"Real fine-tuning artifact for {dataset.name} {dataset_version.version_label}. "
                "The local output is a validated PEFT adapter artifact with a publish-ready manifest, but no Ollama serving model has been created yet."
            ),
            updated_at=now,
        )
        session.add(registry_entry)
        training_job.status = status
        training_job.finished_at = datetime.now(timezone.utc)
        session.commit()
        return get_training_job(session, training_job.id) or {"id": training_job.id}
    except Exception as exc:
        session.rollback()
        failed_job = session.get(FTTrainingJobRecord, training_job_id)
        if failed_job is not None:
            failed_job.status = "failed"
            failed_job.finished_at = datetime.now(timezone.utc)
            failed_job.error_json = {
                "phase": failure_phase,
                "message": str(exc),
            }
            failed_job.log_text = (
                (failed_job.log_text or "")
                + f"\nTraining failed during {failure_phase}: {exc}"
            ).strip()
            session.commit()
        raise


def get_model_artifact(session: Session, artifact_id: str) -> dict[str, Any] | None:
    artifact = session.get(FTModelArtifactRecord, artifact_id)
    return _serialize_artifact(artifact) if artifact is not None else None


def get_training_job_logs(
    session: Session, training_job_id: str
) -> dict[str, Any] | None:
    training_job = session.get(FTTrainingJobRecord, training_job_id)
    if training_job is None:
        return None
    report_artifact = session.scalar(
        select(FTModelArtifactRecord).where(
            FTModelArtifactRecord.training_job_id == training_job_id,
            FTModelArtifactRecord.artifact_type == "training_report",
        )
    )
    return {
        "training_job_id": training_job_id,
        "status": training_job.status,
        "log_text": training_job.log_text,
        "report_artifact": _serialize_artifact(report_artifact),
    }


def get_model_lineage(session: Session, model_id: str) -> dict[str, Any] | None:
    model = session.get(ModelRegistryRecord, model_id)
    if model is None:
        return None
    artifact = (
        session.get(FTModelArtifactRecord, model.artifact_id)
        if model.artifact_id is not None
        else None
    )
    readiness = _serialize_readiness(model)
    return {
        "model_id": model.id,
        "source_type": model.source_type,
        "base_model_name": model.base_model_name,
        "trainer_model_name": _lineage_value(model, "trainer_model_name"),
        "trainer_backend": _artifact_metadata_value(artifact, "trainer_backend")
        or _lineage_value(model, "trainer_backend"),
        "artifact_id": model.artifact_id,
        "artifact_type": artifact.artifact_type if artifact is not None else None,
        "artifact_format": _artifact_metadata_value(artifact, "artifact_format"),
        "published_model_name": model.published_model_name,
        "candidate_published_model_name": _lineage_value(
            model, "candidate_published_model_name"
        ),
        "ollama_model_name": model.ollama_model_name,
        "status": model.status,
        "publish_status": model.publish_status,
        "readiness": readiness,
        "warnings": _model_warnings(model, artifact),
        "lineage_json": model.lineage_json,
    }


def publish_training_job_artifacts(
    session: Session, training_job_id: str
) -> dict[str, Any]:
    training_job = session.get(FTTrainingJobRecord, training_job_id)
    if training_job is None:
        raise KeyError(training_job_id)
    model = session.scalar(
        select(ModelRegistryRecord)
        .join(
            FTModelArtifactRecord,
            FTModelArtifactRecord.id == ModelRegistryRecord.artifact_id,
        )
        .where(FTModelArtifactRecord.training_job_id == training_job_id)
    )
    if model is None:
        raise LookupError("registered model not found for training job")
    if model.publish_status == "published" and model.published_model_name:
        return _serialize_model(
            model, session.get(FTModelArtifactRecord, model.artifact_id)
        )

    settings = get_settings()
    publish_artifact = session.scalar(
        select(FTModelArtifactRecord).where(
            FTModelArtifactRecord.training_job_id == training_job_id,
            FTModelArtifactRecord.artifact_type == "publish_manifest",
        )
    )
    if publish_artifact is None:
        raise LookupError("publish manifest not found for training job")

    manifest = dict(publish_artifact.metadata_json)
    candidate_model_name = str(manifest.get("candidate_model_name") or "").strip()
    if not candidate_model_name:
        model.publish_status = "failed"
        session.commit()
        raise RuntimeError(
            "publish manifest does not include a candidate serving model name"
        )

    model.publish_status = "publish_ready"
    model.status = "artifact_ready"
    model.published_model_name = None
    model.updated_at = datetime.now(timezone.utc)
    publish_metadata = dict(publish_artifact.metadata_json or {})
    publish_metadata["ollama_publish_enabled"] = settings.ollama_publish_enabled
    publish_metadata["status"] = "publish_ready"
    publish_metadata.setdefault("notes", [])
    publish_metadata["notes"] = [
        *publish_metadata["notes"],
        (
            "Automatic Ollama create/import is not implemented in this repository, so publish keeps the model artifact-ready until a real serving model exists."
        ),
    ]
    publish_artifact.metadata_json = publish_metadata
    session.commit()
    return _serialize_model(
        model, session.get(FTModelArtifactRecord, model.artifact_id)
    )
