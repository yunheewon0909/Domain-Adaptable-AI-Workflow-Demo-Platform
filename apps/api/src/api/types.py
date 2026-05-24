from __future__ import annotations

from typing import Any
from typing import TypedDict


class DatasetVersionSummary(TypedDict):
    total: int
    valid: int
    invalid: int
    by_split: dict[str, int]


class DatasetVersionResponse(TypedDict):
    id: str
    dataset_id: str
    version_label: str
    status: str
    row_count: int
    train_split_ratio: float
    val_split_ratio: float
    test_split_ratio: float
    created_at: str | None
    updated_at: str | None
    row_summary: DatasetVersionSummary


class DatasetResponse(TypedDict):
    id: str
    name: str
    task_type: str
    schema_type: str
    description: str | None
    current_version_id: str | None
    created_at: str | None
    updated_at: str | None
    versions: list[DatasetVersionResponse]


class ReadinessResponse(TypedDict):
    selectable: bool
    selectable_reason: str
    publish_status: str
    runtime_ready: bool
    runtime_ready_reason: str


class ArtifactResponse(TypedDict):
    id: str
    training_job_id: str
    artifact_type: str
    local_path: str
    metadata_json: dict[str, Any]
    created_at: str | None


class ModelResponse(TypedDict):
    id: str
    display_name: str
    source_type: str
    base_model_name: str
    trainer_model_name: str | None
    trainer_backend: str | None
    published_model_name: str | None
    candidate_published_model_name: str | None
    serving_model_name: str | None
    artifact_id: str | None
    artifact_type: str | None
    artifact_format: str | None
    artifact_valid: bool | None
    status: str
    publish_status: str
    tags_json: list[str]
    lineage_json: dict[str, Any] | None
    description: str | None
    created_at: str | None
    updated_at: str | None
    artifact: ArtifactResponse | None
    readiness: ReadinessResponse
    warnings: list[str]


class ArtifactPathsResponse(TypedDict):
    dataset_export_dir: str | None
    adapter_dir: str | None
    training_report_path: str | None
    merged_model_dir: str | None
    publish_manifest_path: str | None
    modelfile_template_path: str | None
    training_log_path: str | None


class TrainingJobResponse(TypedDict):
    id: str
    dataset_version_id: str
    dataset_id: str | None
    dataset_name: str | None
    dataset_version_label: str | None
    base_model_name: str
    trainer_model_name: str | None
    training_method: str
    hyperparams_json: dict[str, Any]
    status: str
    trainer_backend: str | None
    device: str | None
    backing_job_id: str | None
    train_rows: int | None
    val_rows: int | None
    test_rows: int | None
    format_summary_json: dict[str, Any] | None
    metrics_json: dict[str, Any] | None
    evaluation_json: dict[str, Any] | None
    error_json: dict[str, Any] | None
    output_dir: str | None
    artifact_paths: ArtifactPathsResponse
    artifact_validation: dict[str, Any] | None
    lineage_warning: str | None
    publish_readiness: dict[str, Any] | None
    log_text: str | None
    created_at: str | None
    started_at: str | None
    finished_at: str | None
    artifacts: list[ArtifactResponse]
    registered_models: list[ModelResponse]
