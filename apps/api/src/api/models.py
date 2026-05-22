from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from api.db import Base


class JobRecord(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_type_status_created_at", "type", "status", "created_at"),
        Index(
            "ix_jobs_workflow_dataset_status_created_at",
            "workflow_key",
            "dataset_key",
            "status",
            "created_at",
        ),
        Index(
            "ix_jobs_dataset_status_created_at", "dataset_key", "status", "created_at"
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'generic'"),
    )
    workflow_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dataset_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("3"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class DatasetRecord(Base):
    __tablename__ = "datasets"
    __table_args__ = (
        Index("ix_datasets_is_active", "is_active"),
        Index("ix_datasets_profile_key", "profile_key"),
    )

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    domain_type: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_dir: Mapped[str] = mapped_column(String(512), nullable=False)
    index_dir: Mapped[str] = mapped_column(String(512), nullable=False)
    db_path: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class FTDatasetRecord(Base):
    __tablename__ = "ft_datasets"
    __table_args__ = (
        Index("ix_ft_datasets_task_type", "task_type"),
        Index("ix_ft_datasets_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_type: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class FTDatasetVersionRecord(Base):
    __tablename__ = "ft_dataset_versions"
    __table_args__ = (
        UniqueConstraint(
            "dataset_id",
            "version_label",
            name="uq_ft_dataset_versions_dataset_version_label",
        ),
        Index("ix_ft_dataset_versions_dataset_id", "dataset_id"),
        Index("ix_ft_dataset_versions_status", "status"),
        Index("ix_ft_dataset_versions_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ft_datasets.id"), nullable=False
    )
    version_label: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'draft'")
    )
    row_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    train_split_ratio: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text("0.8")
    )
    val_split_ratio: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text("0.1")
    )
    test_split_ratio: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text("0.1")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class FTDatasetRowRecord(Base):
    __tablename__ = "ft_dataset_rows"
    __table_args__ = (
        Index("ix_ft_dataset_rows_dataset_version_id", "dataset_version_id"),
        Index("ix_ft_dataset_rows_split", "split"),
        Index("ix_ft_dataset_rows_validation_status", "validation_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_version_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ft_dataset_versions.id"), nullable=False
    )
    split: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'unlabeled'")
    )
    input_json: Mapped[dict[str, Any] | list[Any] | str | None] = mapped_column(
        JSON, nullable=True
    )
    target_json: Mapped[dict[str, Any] | list[Any] | str | None] = mapped_column(
        JSON, nullable=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    validation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'pending'")
    )
    validation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class FTTrainingJobRecord(Base):
    __tablename__ = "ft_training_jobs"
    __table_args__ = (
        UniqueConstraint("backing_job_id", name="uq_ft_training_jobs_backing_job_id"),
        Index("ix_ft_training_jobs_dataset_version_id", "dataset_version_id"),
        Index("ix_ft_training_jobs_status", "status"),
        Index("ix_ft_training_jobs_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_version_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ft_dataset_versions.id"), nullable=False
    )
    base_model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    training_method: Mapped[str] = mapped_column(String(64), nullable=False)
    hyperparams_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'queued'")
    )
    backing_job_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("jobs.id"), nullable=True
    )
    trainer_backend: Mapped[str | None] = mapped_column(String(64), nullable=True)
    train_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    val_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    test_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    format_summary_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    metrics_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    evaluation_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    output_dir: Mapped[str | None] = mapped_column(String(512), nullable=True)
    log_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class FTModelArtifactRecord(Base):
    __tablename__ = "ft_model_artifacts"
    __table_args__ = (
        Index("ix_ft_model_artifacts_training_job_id", "training_job_id"),
        Index("ix_ft_model_artifacts_artifact_type", "artifact_type"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    training_job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ft_training_jobs.id"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    local_path: Mapped[str] = mapped_column(String(512), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class ModelRegistryRecord(Base):
    __tablename__ = "model_registry"
    __table_args__ = (
        Index("ix_model_registry_status", "status"),
        Index("ix_model_registry_source_type", "source_type"),
        Index("ix_model_registry_serving_model_name", "serving_model_name"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    base_model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    serving_model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    published_model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    artifact_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("ft_model_artifacts.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'registered'")
    )
    publish_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'not_requested'")
    )
    tags_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    lineage_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class RAGCollectionRecord(Base):
    __tablename__ = "rag_collections"
    __table_args__ = (
        Index("ix_rag_collections_index_status", "index_status"),
        Index("ix_rag_collections_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    chunking_policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    index_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'ready'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class RAGDocumentRecord(Base):
    __tablename__ = "rag_documents"
    __table_args__ = (
        Index("ix_rag_documents_collection_id", "collection_id"),
        Index("ix_rag_documents_status", "status"),
        Index("ix_rag_documents_mime_type", "mime_type"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("rag_collections.id"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'uploaded'")
    )
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class WorkerHeartbeatRecord(Base):
    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_heartbeat: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
