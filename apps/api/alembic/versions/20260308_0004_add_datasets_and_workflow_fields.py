"""add datasets table and workflow job fields

Revision ID: 20260308_0004
Revises: 20260302_0003
Create Date: 2026-03-08 13:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260308_0004"
down_revision: Union[str, Sequence[str], None] = "20260302_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("domain_type", sa.String(length=64), nullable=False),
        sa.Column("profile_key", sa.String(length=64), nullable=False),
        sa.Column("source_dir", sa.String(length=512), nullable=False),
        sa.Column("index_dir", sa.String(length=512), nullable=False),
        sa.Column("db_path", sa.String(length=512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index("ix_datasets_is_active", "datasets", ["is_active"])
    op.create_index("ix_datasets_profile_key", "datasets", ["profile_key"])

    op.add_column("jobs", sa.Column("workflow_key", sa.String(length=64), nullable=True))
    op.add_column("jobs", sa.Column("dataset_key", sa.String(length=64), nullable=True))
    op.create_index(
        "ix_jobs_workflow_dataset_status_created_at",
        "jobs",
        ["workflow_key", "dataset_key", "status", "created_at"],
    )
    op.create_index(
        "ix_jobs_dataset_status_created_at",
        "jobs",
        ["dataset_key", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_dataset_status_created_at", table_name="jobs")
    op.drop_index("ix_jobs_workflow_dataset_status_created_at", table_name="jobs")
    op.drop_column("jobs", "dataset_key")
    op.drop_column("jobs", "workflow_key")

    op.drop_index("ix_datasets_profile_key", table_name="datasets")
    op.drop_index("ix_datasets_is_active", table_name="datasets")
    op.drop_table("datasets")
