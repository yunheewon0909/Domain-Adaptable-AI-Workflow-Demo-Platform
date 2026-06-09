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
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
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


# --- Graph RAG (ADR 0010) -------------------------------------------------


class RAGChunkRecord(Base):
    __tablename__ = "rag_chunks"
    __table_args__ = (
        Index("ix_rag_chunks_collection_id", "collection_id"),
        Index("ix_rag_chunks_document_id", "document_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("rag_collections.id"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("rag_documents.id"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    embedding_json: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    # Declared last: a column named `text` would otherwise shadow the imported
    # `text()` clause for the server_default calls above within this class body.
    text: Mapped[str] = mapped_column(Text, nullable=False)


class RAGEntityRecord(Base):
    __tablename__ = "rag_entities"
    __table_args__ = (
        Index("ix_rag_entities_collection_id", "collection_id"),
        Index("ix_rag_entities_normalized_name", "normalized_name"),
        Index("ix_rag_entities_community_id", "community_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("rag_collections.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(512), nullable=False)
    type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_json: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    degree: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    community_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class RAGRelationshipRecord(Base):
    __tablename__ = "rag_relationships"
    __table_args__ = (
        Index("ix_rag_relationships_collection_id", "collection_id"),
        Index("ix_rag_relationships_source_entity_id", "source_entity_id"),
        Index("ix_rag_relationships_target_entity_id", "target_entity_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("rag_collections.id"), nullable=False
    )
    source_entity_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("rag_entities.id"), nullable=False
    )
    target_entity_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("rag_entities.id"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("1.0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class RAGEntityChunkRecord(Base):
    __tablename__ = "rag_entity_chunks"
    __table_args__ = (
        Index("ix_rag_entity_chunks_entity_id", "entity_id"),
        Index("ix_rag_entity_chunks_chunk_id", "chunk_id"),
        UniqueConstraint("entity_id", "chunk_id", name="uq_rag_entity_chunk"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("rag_entities.id"), nullable=False
    )
    chunk_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("rag_chunks.id"), nullable=False
    )


class RAGCommunityRecord(Base):
    __tablename__ = "rag_communities"
    __table_args__ = (Index("ix_rag_communities_collection_id", "collection_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("rag_collections.id"), nullable=False
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_embedding_json: Mapped[list[float] | None] = mapped_column(
        JSON, nullable=True
    )
    member_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class RAGCommunityMemberRecord(Base):
    __tablename__ = "rag_community_members"
    __table_args__ = (
        Index("ix_rag_community_members_community_id", "community_id"),
        Index("ix_rag_community_members_entity_id", "entity_id"),
        UniqueConstraint("community_id", "entity_id", name="uq_rag_community_member"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    community_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("rag_communities.id"), nullable=False
    )
    entity_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("rag_entities.id"), nullable=False
    )


class RAGQueryTraceRecord(Base):
    __tablename__ = "rag_query_traces"
    __table_args__ = (Index("ix_rag_query_traces_collection_id", "collection_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("rag_collections.id"), nullable=False
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    embedding_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    results_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


# --- Evaluation (testset generation + runs/reports) -----------------------


class EvaluationSetRecord(Base):
    __tablename__ = "evaluation_sets"
    __table_args__ = (Index("ix_evaluation_sets_collection_id", "collection_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("rag_collections.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'draft'")
    )
    question_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
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


class EvaluationQuestionRecord(Base):
    __tablename__ = "evaluation_questions"
    __table_args__ = (
        Index("ix_evaluation_questions_set_id", "evaluation_set_id"),
        Index("ix_evaluation_questions_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    evaluation_set_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("evaluation_sets.id"), nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'pending'")
    )
    source_chunk_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("rag_chunks.id"), nullable=True
    )
    source_entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
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


class EvaluationRunRecord(Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = (
        Index("ix_evaluation_runs_set_id", "evaluation_set_id"),
        Index("ix_evaluation_runs_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    evaluation_set_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("evaluation_sets.id"), nullable=False
    )
    collection_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("rag_collections.id"), nullable=False
    )
    mode: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'local'")
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'queued'")
    )
    question_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    report_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class EvaluationResultRecord(Base):
    __tablename__ = "evaluation_results"
    __table_args__ = (Index("ix_evaluation_results_run_id", "run_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("evaluation_runs.id"), nullable=False
    )
    question_id: Mapped[str] = mapped_column(String(64), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    generated_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieved_chunk_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    retrieved_entity_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    groundedness: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text("0")
    )
    source_coverage: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text("0")
    )
    hallucination: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
