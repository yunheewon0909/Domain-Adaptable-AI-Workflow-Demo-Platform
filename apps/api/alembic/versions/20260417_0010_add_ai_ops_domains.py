"""add ai ops fine-tuning, models, and rag collection domains

Revision ID: 20260417_0010
Revises: 20260415_0010
Create Date: 2026-04-17 11:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260417_0010"
down_revision: Union[str, Sequence[str], None] = "20260415_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ft_datasets",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("schema_type", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("current_version_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ft_datasets_task_type", "ft_datasets", ["task_type"])
    op.create_index("ix_ft_datasets_created_at", "ft_datasets", ["created_at"])

    op.create_table(
        "ft_dataset_versions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("dataset_id", sa.String(length=64), nullable=False),
        sa.Column("version_label", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column(
            "row_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "train_split_ratio",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.8"),
        ),
        sa.Column(
            "val_split_ratio", sa.Float(), nullable=False, server_default=sa.text("0.1")
        ),
        sa.Column(
            "test_split_ratio",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.1"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["dataset_id"], ["ft_datasets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dataset_id",
            "version_label",
            name="uq_ft_dataset_versions_dataset_version_label",
        ),
    )
    op.create_index(
        "ix_ft_dataset_versions_dataset_id", "ft_dataset_versions", ["dataset_id"]
    )
    op.create_index("ix_ft_dataset_versions_status", "ft_dataset_versions", ["status"])
    op.create_index(
        "ix_ft_dataset_versions_created_at", "ft_dataset_versions", ["created_at"]
    )

    op.create_table(
        "ft_dataset_rows",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("dataset_version_id", sa.String(length=64), nullable=False),
        sa.Column(
            "split",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'unlabeled'"),
        ),
        sa.Column("input_json", sa.JSON(), nullable=True),
        sa.Column("target_json", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column(
            "validation_status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("validation_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["dataset_version_id"], ["ft_dataset_versions.id"]),
    )
    op.create_index(
        "ix_ft_dataset_rows_dataset_version_id",
        "ft_dataset_rows",
        ["dataset_version_id"],
    )
    op.create_index("ix_ft_dataset_rows_split", "ft_dataset_rows", ["split"])
    op.create_index(
        "ix_ft_dataset_rows_validation_status", "ft_dataset_rows", ["validation_status"]
    )

    op.create_table(
        "ft_training_jobs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("dataset_version_id", sa.String(length=64), nullable=False),
        sa.Column("base_model_name", sa.String(length=255), nullable=False),
        sa.Column("training_method", sa.String(length=64), nullable=False),
        sa.Column("hyperparams_json", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column("backing_job_id", sa.String(length=64), nullable=True),
        sa.Column("log_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["dataset_version_id"], ["ft_dataset_versions.id"]),
        sa.ForeignKeyConstraint(["backing_job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "backing_job_id", name="uq_ft_training_jobs_backing_job_id"
        ),
    )
    op.create_index(
        "ix_ft_training_jobs_dataset_version_id",
        "ft_training_jobs",
        ["dataset_version_id"],
    )
    op.create_index("ix_ft_training_jobs_status", "ft_training_jobs", ["status"])
    op.create_index(
        "ix_ft_training_jobs_created_at", "ft_training_jobs", ["created_at"]
    )

    op.create_table(
        "ft_model_artifacts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("training_job_id", sa.String(length=64), nullable=False),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("local_path", sa.String(length=512), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["training_job_id"], ["ft_training_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ft_model_artifacts_training_job_id",
        "ft_model_artifacts",
        ["training_job_id"],
    )
    op.create_index(
        "ix_ft_model_artifacts_artifact_type", "ft_model_artifacts", ["artifact_type"]
    )

    op.create_table(
        "model_registry",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("base_model_name", sa.String(length=255), nullable=False),
        sa.Column("ollama_model_name", sa.String(length=255), nullable=False),
        sa.Column("artifact_id", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'registered'"),
        ),
        sa.Column("tags_json", sa.JSON(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["artifact_id"], ["ft_model_artifacts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_model_registry_status", "model_registry", ["status"])
    op.create_index("ix_model_registry_source_type", "model_registry", ["source_type"])
    op.create_index(
        "ix_model_registry_ollama_model_name", "model_registry", ["ollama_model_name"]
    )

    op.create_table(
        "rag_collections",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("embedding_model", sa.String(length=255), nullable=False),
        sa.Column("chunking_policy_json", sa.JSON(), nullable=False),
        sa.Column(
            "index_status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'ready'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rag_collections_index_status", "rag_collections", ["index_status"]
    )
    op.create_index("ix_rag_collections_created_at", "rag_collections", ["created_at"])

    op.create_table(
        "rag_documents",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'uploaded'"),
        ),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["collection_id"], ["rag_collections.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rag_documents_collection_id", "rag_documents", ["collection_id"]
    )
    op.create_index("ix_rag_documents_status", "rag_documents", ["status"])
    op.create_index("ix_rag_documents_mime_type", "rag_documents", ["mime_type"])


def downgrade() -> None:
    op.drop_index("ix_rag_documents_mime_type", table_name="rag_documents")
    op.drop_index("ix_rag_documents_status", table_name="rag_documents")
    op.drop_index("ix_rag_documents_collection_id", table_name="rag_documents")
    op.drop_table("rag_documents")

    op.drop_index("ix_rag_collections_created_at", table_name="rag_collections")
    op.drop_index("ix_rag_collections_index_status", table_name="rag_collections")
    op.drop_table("rag_collections")

    op.drop_index("ix_model_registry_ollama_model_name", table_name="model_registry")
    op.drop_index("ix_model_registry_source_type", table_name="model_registry")
    op.drop_index("ix_model_registry_status", table_name="model_registry")
    op.drop_table("model_registry")

    op.drop_index(
        "ix_ft_model_artifacts_artifact_type", table_name="ft_model_artifacts"
    )
    op.drop_index(
        "ix_ft_model_artifacts_training_job_id", table_name="ft_model_artifacts"
    )
    op.drop_table("ft_model_artifacts")

    op.drop_index("ix_ft_training_jobs_created_at", table_name="ft_training_jobs")
    op.drop_index("ix_ft_training_jobs_status", table_name="ft_training_jobs")
    op.drop_index(
        "ix_ft_training_jobs_dataset_version_id", table_name="ft_training_jobs"
    )
    op.drop_table("ft_training_jobs")

    op.drop_index("ix_ft_dataset_rows_validation_status", table_name="ft_dataset_rows")
    op.drop_index("ix_ft_dataset_rows_split", table_name="ft_dataset_rows")
    op.drop_index("ix_ft_dataset_rows_dataset_version_id", table_name="ft_dataset_rows")
    op.drop_table("ft_dataset_rows")

    op.drop_index("ix_ft_dataset_versions_created_at", table_name="ft_dataset_versions")
    op.drop_index("ix_ft_dataset_versions_status", table_name="ft_dataset_versions")
    op.drop_index("ix_ft_dataset_versions_dataset_id", table_name="ft_dataset_versions")
    op.drop_table("ft_dataset_versions")

    op.drop_index("ix_ft_datasets_created_at", table_name="ft_datasets")
    op.drop_index("ix_ft_datasets_task_type", table_name="ft_datasets")
    op.drop_table("ft_datasets")
