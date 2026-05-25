from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any
import uuid

logger = logging.getLogger("api.model_registry.service")

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.config import get_settings
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
from api.services.fine_tuning.trainer import (
    is_hf_model_resolution_error,
    run_training_backend,
)

BASE_MODEL_READY_STATUSES = {"active"}
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
# Both `published` (legacy fine-tuned ready) and `active` (what
# publish_training_job_artifacts actually sets on a successful publish)
# count as selectable-ready for the fine_tuned readiness branch.
# Without `active` here, freshly published fine-tuned rows were stuck
# reporting "artifact-ready only" even after LM Studio loaded them.
READY_MODEL_STATUSES = {"published", "active"}
ALLOWED_PUBLISH_STATUSES = {"not_requested", "publish_ready", "published", "failed"}


def _next_prefixed_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _artifacts_root() -> Path:
    settings = get_settings()
    return Path(settings.training_artifact_dir)


def _serialize_readiness(
    model: ModelRegistryRecord,
    *,
    loaded_serving_names: frozenset[str] | None = None,
) -> dict[str, Any]:
    selectable = False
    selectable_reason = "model is not selectable"
    runtime_ready = False
    runtime_ready_reason = "runtime readiness is not available"
    if model.source_type == "base":
        status_ok = model.status in BASE_MODEL_READY_STATUSES
        serving_name = model.serving_model_name or ""
        if loaded_serving_names is None:
            # No probe available — fall back to status-only check (used in
            # unit tests and offline serialization paths).
            selectable = status_ok
            selectable_reason = (
                "base model is registered for direct inference"
                if selectable
                else "base model is not in a ready status"
            )
        else:
            serving_loaded = bool(serving_name) and serving_name in loaded_serving_names
            selectable = status_ok and serving_loaded
            if selectable:
                selectable_reason = (
                    f"base model {serving_name!r} is loaded in LM Studio"
                )
            elif not status_ok:
                selectable_reason = "base model is not in a ready status"
            else:
                selectable_reason = (
                    f"base model {serving_name!r} is not loaded in LM Studio "
                    "(load it in the Local Server tab)"
                )
        runtime_ready = selectable
        runtime_ready_reason = selectable_reason
    elif model.source_type == "fine_tuned":
        published_ok = (
            model.status in READY_MODEL_STATUSES
            and model.publish_status == "published"
            and bool(model.published_model_name)
        )
        if loaded_serving_names is None:
            selectable = published_ok
        else:
            serving_name = model.published_model_name or ""
            selectable = published_ok and bool(serving_name) and serving_name in loaded_serving_names
        runtime_ready = selectable
        if selectable:
            selectable_reason = "fine-tuned model has a published serving target loaded in LM Studio"
            runtime_ready_reason = selectable_reason
        elif published_ok and loaded_serving_names is not None:
            selectable_reason = (
                "Fine-tuned model is staged in LM Studio's models dir but not yet loaded. "
                "Click Load in LM Studio."
            )
            runtime_ready_reason = selectable_reason
        elif model.publish_status == "publish_ready":
            selectable_reason = "Adapter artifacts and a publish manifest are ready, but no LM Studio serving model has been loaded yet."
            runtime_ready_reason = "Automatic LM Studio import is not implemented, so this fine-tuned model remains artifact-only until a real serving model exists."
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
            "This registry entry tracks local adapter/merged-model artifacts. It is not itself an LM Studio serving model."
        )
        if model.publish_status == "publish_ready":
            warnings.append(
                "Publish-ready means a manifest/template exists. Automatic LM Studio import is not implemented by this repository."
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
    explicit = str(
        training_job.hyperparams_json.get("trainer_model_name") or ""
    ).strip()
    if explicit:
        return explicit
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


def _classify_training_failure(*, failure_phase: str, raw_error: str) -> dict[str, Any]:
    normalized_error = raw_error.strip() or "Unknown training failure"
    lowered = normalized_error.lower()
    category = "unknown"
    user_message = f"Training failed during {failure_phase}. Review the technical details below for the captured training error."
    remediation = "Review the raw error, confirm the Mac-native runtime, and retry the smoke job after fixing the reported issue."

    if "rag index" in lowered or "rag.db" in lowered:
        category = "rag_unrelated_failure"
        user_message = "Training failed because the worker reported a RAG/index issue. This is unrelated to fine-tuning artifacts and should be fixed in the retrieval setup first."
        remediation = "Initialize or repair the RAG index path, then retry the fine-tuning job only after the unrelated retrieval problem is resolved."
    elif (
        "locked dataset version" in lowered
        or "dataset version must be validated or locked" in lowered
    ):
        category = "dataset_version_not_locked"
        user_message = "Training failed because the selected dataset version was not locked for real training."
        remediation = "Validate the dataset version, lock it, and then enqueue the smoke job again."
    elif "artifacts failed validation" in lowered:
        category = "artifact_validation_failed"
        user_message = "Training failed during artifact validation. The trainer ran, but the expected adapter/report package was incomplete."
        remediation = "Inspect the artifact directory, confirm adapter/report files were written, and retry after fixing the packaging or validation issue."
    elif (
        "mlx_lm.lora cli is required" in lowered
        or "mlx_lm.fuse cli is required" in lowered
        or "missing mlx training tools" in lowered
    ):
        category = "dependency_missing"
        user_message = "Training failed because required MLX training tooling is missing."
        remediation = "Install or update the Mac-native MLX toolchain (`brew install mlx mlx-lm`), then rerun preflight."
    elif (
        "mlx qlora training failed" in lowered
        or "mlx model fusion failed" in lowered
        or "adapter not found" in lowered
    ):
        category = "mlx_subprocess_failed"
        user_message = "Training failed inside the MLX subprocess. Inspect the training log for the captured mlx_lm.lora/mlx_lm.fuse error."
        remediation = "Open the training.log file under data/model_artifacts/<job_id>/, fix the reported MLX issue, and retry."
    elif "metal" in lowered and ("unavailable" in lowered or "not available" in lowered):
        category = "metal_runtime_unavailable"
        user_message = "Training failed because Apple Silicon Metal is unavailable in the current runtime."
        remediation = "Rerun preflight from the macOS host shell and verify the brew-provided MLX runtime can access Metal."
    elif "smoke fallback failed" in lowered:
        category = "smoke_fallback_failed"
        user_message = "Training failed after the smoke fallback trainer was attempted. The demo fallback path could not finish artifact generation."
        remediation = "Inspect the fallback artifact directory, confirm the deterministic smoke backend is configured, and retry the smoke job."
    elif is_hf_model_resolution_error(normalized_error):
        category = "hf_model_download_failure"
        user_message = (
            "Training failed while downloading or resolving the tiny trainer model."
        )
        remediation = "Check network access, model credentials if needed, or use a locally cached trainer_model_name before retrying the smoke job."

    return {
        "phase": failure_phase,
        "category": category,
        "message": user_message,
        "user_message": user_message,
        "remediation": remediation,
        "raw_error": normalized_error,
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
    model: ModelRegistryRecord,
    artifact: FTModelArtifactRecord | None,
    *,
    loaded_serving_names: frozenset[str] | None = None,
) -> dict[str, Any]:
    effective_serving_name = model.serving_model_name
    if model.source_type == "fine_tuned":
        effective_serving_name = model.published_model_name
    readiness = _serialize_readiness(model, loaded_serving_names=loaded_serving_names)
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
        "published_model_name": model.published_model_name,
        "candidate_published_model_name": _lineage_value(
            model, "candidate_published_model_name"
        ),
        "serving_model_name": effective_serving_name,
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
    configured_default_name = (settings.lmstudio_chat_model or "").strip()
    if not configured_default_name:
        # No LM Studio chat model configured yet; nothing to seed.
        return []

    defaults = [
        {
            "display_name": "Default LM Studio model",
            "base_model_name": configured_default_name,
            "serving_model_name": configured_default_name,
            "status": "active",
            "description": "Default LM Studio serving model used for grounded chat and inference.",
            "tags_json": ["base", "default"],
        }
    ]

    now = datetime.now(timezone.utc)
    # Retire any auto-seeded base row that does not match the configured
    # chat model. "Auto-seeded" = base + tagged 'default' or 'fallback'.
    # User-created or fine-tuned rows are left untouched.
    stale_seeds = session.scalars(
        select(ModelRegistryRecord).where(
            ModelRegistryRecord.source_type == "base",
            ModelRegistryRecord.serving_model_name != configured_default_name,
        )
    ).all()
    for model in stale_seeds:
        tags = list(model.tags_json or [])
        # Anything whose display_name starts with "Default " was originally
        # auto-seeded by this function. Earlier versions of the demote
        # branch stripped the "default" tag, turning those rows into
        # immortal zombies; treat the display_name as the authoritative
        # marker so they get cleaned up regardless of tag drift.
        is_auto_seed = (
            "default" in tags
            or "fallback" in tags
            or (model.display_name or "").startswith("Default ")
        )
        if is_auto_seed:
            session.delete(model)
        elif model.status == "active":
            # User-promoted non-auto-seed pointing the wrong way — demote
            # so we don't lose user-curated history.
            model.status = "registered"

    for item in defaults:
        existing = session.scalar(
            select(ModelRegistryRecord).where(
                ModelRegistryRecord.serving_model_name == item["serving_model_name"]
            )
        )
        if existing is not None:
            existing.display_name = item["display_name"]
            existing.base_model_name = item["base_model_name"]
            existing.source_type = "base"
            existing.status = item["status"]
            existing.publish_status = "published"
            existing.published_model_name = item["serving_model_name"]
            existing.tags_json = item["tags_json"]
            existing.description = item["description"]
            continue
        session.add(
            ModelRegistryRecord(
                id=_next_prefixed_id("model"),
                display_name=item["display_name"],
                source_type="base",
                base_model_name=item["base_model_name"],
                serving_model_name=item["serving_model_name"],
                published_model_name=item["serving_model_name"],
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
    from api.services.model_registry.lmstudio_register import loaded_lmstudio_models

    settings = get_settings()
    loaded = loaded_lmstudio_models(base_url=settings.lmstudio_base_url)

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
            loaded_serving_names=loaded,
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
    if resolved_training_method == "sft_qlora" and dataset_version.status != "locked":
        raise ValueError("real sft_qlora training requires a locked dataset version")

    base_model_clean = base_model_name.strip()
    trainer_backend = get_settings().ft_trainer_backend
    hyperparams = hyperparams_json or {}
    training_job = FTTrainingJobRecord(
        id=_next_prefixed_id("ft-job"),
        dataset_version_id=dataset_version_id,
        base_model_name=base_model_clean,
        training_method=resolved_training_method,
        hyperparams_json=hyperparams,
        trainer_backend=trainer_backend,
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
    serving_model_name: str | None = None,
) -> dict[str, Any]:
    ensure_default_models(session)
    if model_id and serving_model_name:
        raise ValueError("provide either model_id or serving_model_name, not both")
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
    if serving_model_name:
        model = session.scalar(
            select(ModelRegistryRecord).where(
                ModelRegistryRecord.serving_model_name == serving_model_name
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
            "display_name": serving_model_name,
            "source_type": "direct",
            "base_model_name": serving_model_name,
            "serving_model_name": serving_model_name,
            "artifact_id": None,
            "status": "direct",
            "tags_json": ["direct"],
            "description": "Direct LM Studio model selection outside the registry.",
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
            require_locked=training_job.training_method == "sft_qlora",
        )
        training_job.train_rows = export_result.row_counts.get("train")
        training_job.val_rows = export_result.row_counts.get("val")
        training_job.test_rows = export_result.row_counts.get("test")
        training_job.format_summary_json = export_result.format_summary
        training_job.output_dir = str(artifact_dir)
        training_job.status = "training"
        failure_phase = "training"
        # Commit the phase transition so the demo poller sees `training`
        # while the long-running MLX subprocess is still busy. Without this,
        # the row stays in `preparing_data` (or `queued` from a viewer's
        # perspective due to transaction isolation) until the whole job
        # finishes, which can be minutes-to-hours.
        session.commit()

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
            f"Validated adapter artifact at {training_output.adapter_dir}."
        )

        dataset_export_artifact = FTModelArtifactRecord(
            id=_next_prefixed_id("artifact"),
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
            id=_next_prefixed_id("artifact"),
            training_job_id=training_job.id,
            artifact_type=artifact_type,
            local_path=training_output.adapter_dir,
            metadata_json={
                "training_job_id": training_job.id,
                "dataset_version_id": dataset_version.id,
                "base_model_name": training_job.base_model_name,
                "trainer_model_name": training_output.trainer_model_name,
                "trainer_backend": training_output.trainer_backend,
                "artifact_format": artifact_validation.get("artifact_format", "adapter"),
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
            id=_next_prefixed_id("artifact"),
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
                id=_next_prefixed_id("artifact"),
                training_job_id=training_job.id,
                artifact_type="merged_model",
                local_path=training_output.merged_model_dir,
                metadata_json={
                    "status": "ready",
                    "artifact_format": "mlx_fused_model",
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
            id=_next_prefixed_id("artifact"),
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
            id=_next_prefixed_id("model"),
            display_name=f"{dataset.name} {dataset_version.version_label}",
            source_type="fine_tuned",
            base_model_name=training_job.base_model_name,
            serving_model_name=f"artifact::{training_job.id}",
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
                "artifact_format": artifact_validation.get("artifact_format", "adapter"),
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
                f"Deterministic smoke fallback artifact for {dataset.name} {dataset_version.version_label}. "
                "This validates the dataset/export/artifact/registry pipeline for demo smoke runs, but it does not validate model quality or create an LM Studio serving model."
                if artifact_validation.get("smoke_fallback_used")
                else f"Real fine-tuning artifact for {dataset.name} {dataset_version.version_label}. "
                "The local output is a validated MLX adapter/merged-model artifact with a publish-ready manifest, but no LM Studio serving model has been loaded yet."
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
            failed_job.error_json = _classify_training_failure(
                failure_phase=failure_phase,
                raw_error=str(exc),
            )
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
    # Tail the on-disk training.log so the demo poller can show live
    # subprocess output while `mlx_lm.lora` is still running. The file
    # lives at a deterministic path under the artifact dir; it may not
    # exist yet during the very first seconds of the run, or for a
    # deterministic_smoke job that wrote a tiny synthetic log.
    log_tail: str | None = None
    log_path = _artifacts_root() / training_job_id / "trainer_output" / "training.log"
    if log_path.is_file():
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        # Cap to the last ~16 KB so a long run doesn't bloat the response.
        if len(text) > 16384:
            text = text[-16384:]
        log_tail = text or None
    return {
        "training_job_id": training_job_id,
        "status": training_job.status,
        "log_text": training_job.log_text,
        "log_tail": log_tail,
        "log_path": str(log_path) if log_path.is_file() else None,
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
        "serving_model_name": model.serving_model_name,
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

    namespace, _, model_basename = candidate_model_name.partition("/")
    if not model_basename:
        namespace = settings.mlx_model_namespace or "platform"
        model_basename = candidate_model_name

    publish_metadata = dict(publish_artifact.metadata_json or {})
    publish_metadata["adapter_publish_enabled"] = settings.adapter_publish_enabled

    register_summary = _register_with_lmstudio(
        session,
        training_job_id=training_job_id,
        namespace=namespace,
        model_basename=model_basename,
        settings=settings,
    )
    publish_metadata["lmstudio_register"] = register_summary

    # Auto-load the fused model into LM Studio so it becomes immediately
    # selectable without requiring the user to manually click "Load" in the UI.
    if register_summary.get("registered") and candidate_model_name:
        _lms_load_model(candidate_model_name)

    lmstudio_loaded = _probe_lmstudio(
        base_url=settings.lmstudio_base_url, model_id=candidate_model_name
    )
    publish_metadata["lmstudio_model_loaded"] = lmstudio_loaded

    now = datetime.now(timezone.utc)
    if lmstudio_loaded:
        model.publish_status = "published"
        model.status = "active"
        model.published_model_name = candidate_model_name
        model.serving_model_name = candidate_model_name
        publish_metadata["status"] = "published"
        publish_metadata["notes"] = [
            *publish_metadata.get("notes", []),
            (
                f"Fused MLX model is loaded in LM Studio as {candidate_model_name}; "
                "registry row is now selectable for inference."
            ),
        ]
    else:
        model.publish_status = "publish_ready"
        model.status = "artifact_ready"
        model.published_model_name = None
        publish_metadata["status"] = "publish_ready"
        publish_metadata["notes"] = [
            *publish_metadata.get("notes", []),
            (
                f"Fused MLX model staged for LM Studio as '{candidate_model_name}'. "
                "Open LM Studio, load the model, then re-publish (or wait for the next "
                "probe) to mark the registry row selectable."
            ),
        ]
    publish_artifact.metadata_json = publish_metadata
    session.commit()
    return _serialize_model(
        model, session.get(FTModelArtifactRecord, model.artifact_id)
    )


def _lms_load_model(candidate_model_name: str) -> bool:
    """Try to load a freshly published model into LM Studio via the lms CLI.

    Called after register_fused_model places the model files under LM Studio's
    models directory. Uses ``lms ls --json`` to discover the proper modelKey,
    then ``lms load <modelKey> --gpu max --exact`` to load it.

    Returns True on success, False when lms is unavailable or the load command
    fails — the caller handles failure gracefully (model stays in
    artifact_ready/publish_ready state and the user can load it manually).
    """
    import shutil
    import subprocess
    from pathlib import Path as _Path

    lms: str | None = shutil.which("lms")
    if lms is None:
        candidate = _Path.home() / ".lmstudio" / "bin" / "lms"
        lms = str(candidate) if candidate.is_file() else None
    if lms is None:
        logger.warning(
            "publish_auto_load: lms CLI not found; skipping auto-load of %r",
            candidate_model_name,
        )
        return False

    # Discover the proper modelKey from lms ls rather than guessing.
    try:
        ls_result = subprocess.run(
            [lms, "ls", "--json"],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("publish_auto_load: lms ls failed: %s", exc)
        return False
    if ls_result.returncode != 0:
        logger.warning("publish_auto_load: lms ls exit %d: %s",
                       ls_result.returncode, ls_result.stderr.strip()[:300])
        return False

    import json as _json
    try:
        listing = _json.loads(ls_result.stdout)
    except _json.JSONDecodeError as exc:
        logger.warning("publish_auto_load: lms ls non-JSON: %s", exc)
        return False
    if not isinstance(listing, list):
        logger.warning("publish_auto_load: lms ls unexpected shape")
        return False

    # Find an LLM entry whose modelKey or indexedModelIdentifier matches.
    target = None
    for entry in listing:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != "llm":
            continue
        key = str(entry.get("modelKey") or "")
        indexed = str(entry.get("indexedModelIdentifier") or "")
        if key == candidate_model_name or indexed == candidate_model_name:
            target = entry
            break
    if target is None:
        logger.warning(
            "publish_auto_load: %r not found in lms ls; indexed LLMs: %s",
            candidate_model_name,
            [e.get("modelKey") for e in listing
             if isinstance(e, dict) and e.get("type") == "llm"],
        )
        return False

    model_key = str(target.get("modelKey") or "")
    if not model_key:
        logger.warning("publish_auto_load: selected model has no modelKey; aborting")
        return False

    indexed_id = str(target.get("indexedModelIdentifier") or "")
    logger.info("publish_auto_load: loading %r into LM Studio...", model_key)
    try:
        cmd = [lms, "load", model_key, "--gpu", "max", "--exact"]
        if indexed_id:
            cmd.extend(["--identifier", indexed_id])
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("publish_auto_load: lms load failed: %s", exc)
        return False
    if result.returncode != 0:
        logger.warning(
            "publish_auto_load: lms load exit %d: %s",
            result.returncode,
            result.stderr.strip()[:300],
        )
        return False
    logger.info("publish_auto_load: %r loaded successfully", model_key)
    return True


def _register_with_lmstudio(
    session: Session,
    *,
    training_job_id: str,
    namespace: str,
    model_basename: str,
    settings: Any,
) -> dict[str, Any]:
    from pathlib import Path as _Path

    from api.services.model_registry.lmstudio_register import register_fused_model

    merged_artifact = session.scalar(
        select(FTModelArtifactRecord).where(
            FTModelArtifactRecord.training_job_id == training_job_id,
            FTModelArtifactRecord.artifact_type == "merged_model",
        )
    )
    if merged_artifact is None or not merged_artifact.local_path:
        return {
            "registered": False,
            "reason": "no merged_model artifact was produced (smoke fallback?); skipping LM Studio register",
            "target_dir": None,
        }
    result = register_fused_model(
        fused_model_dir=_Path(merged_artifact.local_path),
        lmstudio_models_dir=_Path(settings.lmstudio_models_dir),
        namespace=namespace,
        model_name=model_basename,
    )
    return {
        "registered": result.target_dir is not None,
        "target_dir": str(result.target_dir) if result.target_dir else None,
        "used_symlinks": result.used_symlinks,
        "copied_file_count": result.copied_file_count,
        "detail": result.detail,
    }


def _probe_lmstudio(*, base_url: str, model_id: str) -> bool:
    from api.services.model_registry.lmstudio_register import (
        invalidate_loaded_cache,
        probe_lmstudio_for_model,
    )

    # Publish is an explicit "load this now" gesture by the reviewer, so
    # bypass the 30s `loaded_lmstudio_models` cache once and read LM Studio
    # fresh. Without this, a reviewer who loads the model in LM Studio
    # immediately after the first publish call sees stale "not loaded"
    # for up to 30s.
    invalidate_loaded_cache()
    return probe_lmstudio_for_model(base_url=base_url, model_id=model_id)
