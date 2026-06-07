"""drop fine-tuning + model registry tables (fine-tuning removed from core)

Fine-tuning was removed from the product (ADR 0008). This drops the FT dataset/
training/artifact tables and the model_registry table together with the code
removal. Downgrade recreates the tables (empty) so the chain stays reversible;
prior data is not restored.

Revision ID: 20260607_0016
Revises: 20260525_0015
Create Date: 2026-06-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260607_0016"
down_revision: Union[str, Sequence[str], None] = "20260525_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Drop in FK-dependency order: model_registry → ft_model_artifacts →
# ft_training_jobs → ft_dataset_rows → ft_dataset_versions → ft_datasets.
_DROP_ORDER = [
    "model_registry",
    "ft_model_artifacts",
    "ft_training_jobs",
    "ft_dataset_rows",
    "ft_dataset_versions",
    "ft_datasets",
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    for table in _DROP_ORDER:
        if table in existing:
            op.drop_table(table)


def downgrade() -> None:
    op.create_table(
        "ft_datasets",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
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
    )
    op.create_table(
        "ft_dataset_versions",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "dataset_id",
            sa.String(length=64),
            sa.ForeignKey("ft_datasets.id"),
            nullable=False,
        ),
        sa.Column("version_label", sa.String(length=64), nullable=False),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default=sa.text("'draft'")
        ),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "train_split_ratio", sa.Float(), nullable=False, server_default=sa.text("0.8")
        ),
        sa.Column(
            "val_split_ratio", sa.Float(), nullable=False, server_default=sa.text("0.1")
        ),
        sa.Column(
            "test_split_ratio", sa.Float(), nullable=False, server_default=sa.text("0.1")
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
        sa.UniqueConstraint(
            "dataset_id",
            "version_label",
            name="uq_ft_dataset_versions_dataset_version_label",
        ),
    )
    op.create_table(
        "ft_dataset_rows",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "dataset_version_id",
            sa.String(length=64),
            sa.ForeignKey("ft_dataset_versions.id"),
            nullable=False,
        ),
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
    )
    op.create_table(
        "ft_training_jobs",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "dataset_version_id",
            sa.String(length=64),
            sa.ForeignKey("ft_dataset_versions.id"),
            nullable=False,
        ),
        sa.Column("base_model_name", sa.String(length=255), nullable=False),
        sa.Column("training_method", sa.String(length=64), nullable=False),
        sa.Column("hyperparams_json", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column(
            "backing_job_id",
            sa.String(length=64),
            sa.ForeignKey("jobs.id"),
            nullable=True,
        ),
        sa.Column("trainer_backend", sa.String(length=64), nullable=True),
        sa.Column("train_rows", sa.Integer(), nullable=True),
        sa.Column("val_rows", sa.Integer(), nullable=True),
        sa.Column("test_rows", sa.Integer(), nullable=True),
        sa.Column("format_summary_json", sa.JSON(), nullable=True),
        sa.Column("metrics_json", sa.JSON(), nullable=True),
        sa.Column("evaluation_json", sa.JSON(), nullable=True),
        sa.Column("error_json", sa.JSON(), nullable=True),
        sa.Column("output_dir", sa.String(length=512), nullable=True),
        sa.Column("log_text", sa.Text(), nullable=True),
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
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("backing_job_id", name="uq_ft_training_jobs_backing_job_id"),
    )
    op.create_table(
        "ft_model_artifacts",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "training_job_id",
            sa.String(length=64),
            sa.ForeignKey("ft_training_jobs.id"),
            nullable=False,
        ),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("local_path", sa.String(length=512), nullable=False),
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
    )
    op.create_table(
        "model_registry",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("base_model_name", sa.String(length=255), nullable=False),
        sa.Column("serving_model_name", sa.String(length=255), nullable=False),
        sa.Column("published_model_name", sa.String(length=255), nullable=True),
        sa.Column(
            "artifact_id",
            sa.String(length=64),
            sa.ForeignKey("ft_model_artifacts.id"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'registered'"),
        ),
        sa.Column(
            "publish_status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'not_requested'"),
        ),
        sa.Column("tags_json", sa.JSON(), nullable=False),
        sa.Column("lineage_json", sa.JSON(), nullable=True),
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
    )
