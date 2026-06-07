"""add evaluation_runs + evaluation_results (RAG evaluation + reports)

See ADR 0008 / docs/open-webui-docker-migration.md Phase 7.

Revision ID: 20260607_0019
Revises: 20260607_0018
Create Date: 2026-06-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260607_0019"
down_revision: Union[str, Sequence[str], None] = "20260607_0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "evaluation_set_id",
            sa.String(length=64),
            sa.ForeignKey("evaluation_sets.id"),
            nullable=False,
        ),
        sa.Column(
            "collection_id",
            sa.String(length=64),
            sa.ForeignKey("rag_collections.id"),
            nullable=False,
        ),
        sa.Column("mode", sa.String(length=32), nullable=False, server_default=sa.text("'local'")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("question_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("report_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_evaluation_runs_set_id", "evaluation_runs", ["evaluation_set_id"])
    op.create_index("ix_evaluation_runs_status", "evaluation_runs", ["status"])

    op.create_table(
        "evaluation_results",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("evaluation_runs.id"),
            nullable=False,
        ),
        sa.Column("question_id", sa.String(length=64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("generated_answer", sa.Text(), nullable=True),
        sa.Column("retrieved_chunk_ids_json", sa.JSON(), nullable=False),
        sa.Column("retrieved_entity_ids_json", sa.JSON(), nullable=False),
        sa.Column("groundedness", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("source_coverage", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("hallucination", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_evaluation_results_run_id", "evaluation_results", ["run_id"])


def downgrade() -> None:
    op.drop_table("evaluation_results")
    op.drop_table("evaluation_runs")
