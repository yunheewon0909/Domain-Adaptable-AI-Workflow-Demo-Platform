from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
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
        onupdate=func.now(),
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
    source_dir: Mapped[str] = mapped_column(String(512), nullable=False)  # DEPRECATED: legacy ingest path, no longer used by any service
    index_dir: Mapped[str] = mapped_column(String(512), nullable=False)  # DEPRECATED: legacy ingest path, no longer used by any service
    db_path: Mapped[str] = mapped_column(String(512), nullable=False)  # DEPRECATED: legacy ingest path, no longer used by any service
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
        onupdate=func.now(),
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
        onupdate=func.now(),
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
        onupdate=func.now(),
    )
