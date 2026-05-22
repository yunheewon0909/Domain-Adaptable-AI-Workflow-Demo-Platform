"""rename model_registry.ollama_model_name to serving_model_name

Revision ID: 20260523_0014
Revises: 20260523_0013
Create Date: 2026-05-23 21:00:00

The Mac-native transition removed Ollama as the serving runtime. The DB
column kept its legacy name through earlier waves; this migration renames
it to `serving_model_name` to match the new code/API surface and drops the
old index in favor of a same-shape index on the new column.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


revision: str = "20260523_0014"
down_revision: Union[str, Sequence[str], None] = "20260523_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("model_registry"):
        return
    existing_columns = {col["name"] for col in inspector.get_columns("model_registry")}
    existing_indexes = {
        idx["name"] for idx in inspector.get_indexes("model_registry") if idx.get("name")
    }
    if "ix_model_registry_ollama_model_name" in existing_indexes:
        op.drop_index("ix_model_registry_ollama_model_name", table_name="model_registry")
    if "ollama_model_name" in existing_columns and "serving_model_name" not in existing_columns:
        with op.batch_alter_table("model_registry") as batch_op:
            batch_op.alter_column(
                "ollama_model_name", new_column_name="serving_model_name"
            )
    op.create_index(
        "ix_model_registry_serving_model_name",
        "model_registry",
        ["serving_model_name"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("model_registry"):
        return
    existing_indexes = {
        idx["name"] for idx in inspector.get_indexes("model_registry") if idx.get("name")
    }
    if "ix_model_registry_serving_model_name" in existing_indexes:
        op.drop_index(
            "ix_model_registry_serving_model_name", table_name="model_registry"
        )
    existing_columns = {col["name"] for col in inspector.get_columns("model_registry")}
    if "serving_model_name" in existing_columns and "ollama_model_name" not in existing_columns:
        with op.batch_alter_table("model_registry") as batch_op:
            batch_op.alter_column(
                "serving_model_name", new_column_name="ollama_model_name"
            )
    op.create_index(
        "ix_model_registry_ollama_model_name",
        "model_registry",
        ["ollama_model_name"],
    )
