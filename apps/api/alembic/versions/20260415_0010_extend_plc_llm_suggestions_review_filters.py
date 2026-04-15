"""extend plc llm suggestions review filters

Revision ID: 20260415_0010
Revises: 20260415_0009
Create Date: 2026-04-15 17:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260415_0010"
down_revision: Union[str, Sequence[str], None] = "20260415_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("plc_llm_suggestions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "payload_schema_version",
                sa.String(length=64),
                nullable=False,
                server_default=sa.text("'plc-llm-suggestion.v1'"),
            )
        )
    op.create_index(
        "ix_plc_llm_suggestions_type_status",
        "plc_llm_suggestions",
        ["suggestion_type", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_plc_llm_suggestions_type_status", table_name="plc_llm_suggestions"
    )
    with op.batch_alter_table("plc_llm_suggestions") as batch_op:
        batch_op.drop_column("payload_schema_version")
