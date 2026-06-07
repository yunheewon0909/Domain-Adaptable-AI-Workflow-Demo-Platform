"""add evaluation_sets + evaluation_questions (testset generation)

Repurposes the former Q/A generator as reviewable evaluation testsets linked to
source chunks/entities. See ADR 0008.

Revision ID: 20260607_0018
Revises: 20260607_0017
Create Date: 2026-06-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260607_0018"
down_revision: Union[str, Sequence[str], None] = "20260607_0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "evaluation_sets",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "collection_id",
            sa.String(length=64),
            sa.ForeignKey("rag_collections.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default=sa.text("'draft'")
        ),
        sa.Column(
            "question_count", sa.Integer(), nullable=False, server_default=sa.text("0")
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
    )
    op.create_index(
        "ix_evaluation_sets_collection_id", "evaluation_sets", ["collection_id"]
    )

    op.create_table(
        "evaluation_questions",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "evaluation_set_id",
            sa.String(length=64),
            sa.ForeignKey("evaluation_sets.id"),
            nullable=False,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "source_chunk_id",
            sa.String(length=64),
            sa.ForeignKey("rag_chunks.id"),
            nullable=True,
        ),
        sa.Column("source_entity_id", sa.String(length=64), nullable=True),
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
    op.create_index(
        "ix_evaluation_questions_set_id",
        "evaluation_questions",
        ["evaluation_set_id"],
    )
    op.create_index(
        "ix_evaluation_questions_status", "evaluation_questions", ["status"]
    )


def downgrade() -> None:
    op.drop_table("evaluation_questions")
    op.drop_table("evaluation_sets")
