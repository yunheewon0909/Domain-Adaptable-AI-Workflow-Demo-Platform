"""upgrade fine-tuning scaffold toward real sft mvp

Revision ID: 20260417_0011
Revises: 20260417_0010
Create Date: 2026-04-17 19:30:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260417_0011"
down_revision: Union[str, Sequence[str], None] = "20260417_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ft_training_jobs",
        sa.Column("trainer_backend", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "ft_training_jobs",
        sa.Column("train_rows", sa.Integer(), nullable=True),
    )
    op.add_column(
        "ft_training_jobs",
        sa.Column("val_rows", sa.Integer(), nullable=True),
    )
    op.add_column(
        "ft_training_jobs",
        sa.Column("test_rows", sa.Integer(), nullable=True),
    )
    op.add_column(
        "ft_training_jobs",
        sa.Column("format_summary_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "ft_training_jobs",
        sa.Column("metrics_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "ft_training_jobs",
        sa.Column("evaluation_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "ft_training_jobs",
        sa.Column("error_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "ft_training_jobs",
        sa.Column("output_dir", sa.String(length=512), nullable=True),
    )

    op.add_column(
        "model_registry",
        sa.Column("published_model_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "model_registry",
        sa.Column(
            "publish_status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'not_requested'"),
        ),
    )
    op.add_column(
        "model_registry",
        sa.Column("lineage_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_registry", "lineage_json")
    op.drop_column("model_registry", "publish_status")
    op.drop_column("model_registry", "published_model_name")

    op.drop_column("ft_training_jobs", "output_dir")
    op.drop_column("ft_training_jobs", "error_json")
    op.drop_column("ft_training_jobs", "evaluation_json")
    op.drop_column("ft_training_jobs", "metrics_json")
    op.drop_column("ft_training_jobs", "format_summary_json")
    op.drop_column("ft_training_jobs", "test_rows")
    op.drop_column("ft_training_jobs", "val_rows")
    op.drop_column("ft_training_jobs", "train_rows")
    op.drop_column("ft_training_jobs", "trainer_backend")
