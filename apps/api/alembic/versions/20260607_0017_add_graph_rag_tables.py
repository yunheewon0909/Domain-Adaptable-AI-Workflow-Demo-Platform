"""add Graph RAG tables: chunks, entities, relationships, communities, traces

See ADR 0010. Postgres property graph for in-repo Graph RAG. Embeddings stored
as JSON; cosine in Python at demo scale.

Revision ID: 20260607_0017
Revises: 20260607_0016
Create Date: 2026-06-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260607_0017"
down_revision: Union[str, Sequence[str], None] = "20260607_0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rag_chunks",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "collection_id",
            sa.String(length=64),
            sa.ForeignKey("rag_collections.id"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.String(length=64),
            sa.ForeignKey("rag_documents.id"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("embedding_json", sa.JSON(), nullable=True),
        sa.Column("embedding_model", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_rag_chunks_collection_id", "rag_chunks", ["collection_id"])
    op.create_index("ix_rag_chunks_document_id", "rag_chunks", ["document_id"])

    op.create_table(
        "rag_entities",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "collection_id",
            sa.String(length=64),
            sa.ForeignKey("rag_collections.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("normalized_name", sa.String(length=512), nullable=False),
        sa.Column("type", sa.String(length=128), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("embedding_json", sa.JSON(), nullable=True),
        sa.Column("degree", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("community_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_rag_entities_collection_id", "rag_entities", ["collection_id"])
    op.create_index(
        "ix_rag_entities_normalized_name", "rag_entities", ["normalized_name"]
    )
    op.create_index("ix_rag_entities_community_id", "rag_entities", ["community_id"])

    op.create_table(
        "rag_relationships",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "collection_id",
            sa.String(length=64),
            sa.ForeignKey("rag_collections.id"),
            nullable=False,
        ),
        sa.Column(
            "source_entity_id",
            sa.String(length=64),
            sa.ForeignKey("rag_entities.id"),
            nullable=False,
        ),
        sa.Column(
            "target_entity_id",
            sa.String(length=64),
            sa.ForeignKey("rag_entities.id"),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("weight", sa.Float(), nullable=False, server_default=sa.text("1.0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_rag_relationships_collection_id", "rag_relationships", ["collection_id"]
    )
    op.create_index(
        "ix_rag_relationships_source_entity_id",
        "rag_relationships",
        ["source_entity_id"],
    )
    op.create_index(
        "ix_rag_relationships_target_entity_id",
        "rag_relationships",
        ["target_entity_id"],
    )

    op.create_table(
        "rag_entity_chunks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "entity_id",
            sa.String(length=64),
            sa.ForeignKey("rag_entities.id"),
            nullable=False,
        ),
        sa.Column(
            "chunk_id",
            sa.String(length=64),
            sa.ForeignKey("rag_chunks.id"),
            nullable=False,
        ),
        sa.UniqueConstraint("entity_id", "chunk_id", name="uq_rag_entity_chunk"),
    )
    op.create_index(
        "ix_rag_entity_chunks_entity_id", "rag_entity_chunks", ["entity_id"]
    )
    op.create_index("ix_rag_entity_chunks_chunk_id", "rag_entity_chunks", ["chunk_id"])

    op.create_table(
        "rag_communities",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "collection_id",
            sa.String(length=64),
            sa.ForeignKey("rag_collections.id"),
            nullable=False,
        ),
        sa.Column("level", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("summary_embedding_json", sa.JSON(), nullable=True),
        sa.Column("member_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_rag_communities_collection_id", "rag_communities", ["collection_id"]
    )

    op.create_table(
        "rag_community_members",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "community_id",
            sa.String(length=64),
            sa.ForeignKey("rag_communities.id"),
            nullable=False,
        ),
        sa.Column(
            "entity_id",
            sa.String(length=64),
            sa.ForeignKey("rag_entities.id"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "community_id", "entity_id", name="uq_rag_community_member"
        ),
    )
    op.create_index(
        "ix_rag_community_members_community_id",
        "rag_community_members",
        ["community_id"],
    )
    op.create_index(
        "ix_rag_community_members_entity_id", "rag_community_members", ["entity_id"]
    )

    op.create_table(
        "rag_query_traces",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "collection_id",
            sa.String(length=64),
            sa.ForeignKey("rag_collections.id"),
            nullable=False,
        ),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("embedding_model", sa.String(length=255), nullable=True),
        sa.Column("results_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_rag_query_traces_collection_id", "rag_query_traces", ["collection_id"]
    )


def downgrade() -> None:
    op.drop_table("rag_query_traces")
    op.drop_table("rag_community_members")
    op.drop_table("rag_communities")
    op.drop_table("rag_entity_chunks")
    op.drop_table("rag_relationships")
    op.drop_table("rag_entities")
    op.drop_table("rag_chunks")
