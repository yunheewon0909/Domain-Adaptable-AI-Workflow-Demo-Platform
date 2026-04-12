"""add plc llm suggestions

Revision ID: 20260412_0008
Revises: 20260412_0007
Create Date: 2026-04-12 22:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260412_0008"
down_revision = "20260412_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plc_llm_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("suite_id", sa.String(length=64), nullable=True),
        sa.Column("testcase_id", sa.String(length=128), nullable=True),
        sa.Column("suggestion_type", sa.String(length=64), nullable=False),
        sa.Column("source_payload_json", sa.JSON(), nullable=False),
        sa.Column("suggestion_payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["suite_id"], ["plc_test_suites.id"]),
        sa.ForeignKeyConstraint(["testcase_id"], ["plc_testcases.id"]),
    )
    op.create_index(
        "ix_plc_llm_suggestions_status_created_at",
        "plc_llm_suggestions",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_plc_llm_suggestions_suite_id",
        "plc_llm_suggestions",
        ["suite_id"],
    )
    op.create_index(
        "ix_plc_llm_suggestions_testcase_id",
        "plc_llm_suggestions",
        ["testcase_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_plc_llm_suggestions_testcase_id", table_name="plc_llm_suggestions"
    )
    op.drop_index("ix_plc_llm_suggestions_suite_id", table_name="plc_llm_suggestions")
    op.drop_index(
        "ix_plc_llm_suggestions_status_created_at", table_name="plc_llm_suggestions"
    )
    op.drop_table("plc_llm_suggestions")
