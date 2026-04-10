"""add plc test suites and job fields

Revision ID: 20260411_0005
Revises: 20260308_0004
Create Date: 2026-04-11 18:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260411_0005"
down_revision: Union[str, Sequence[str], None] = "20260308_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plc_test_suites",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("source_filename", sa.String(length=255), nullable=False),
        sa.Column("source_format", sa.String(length=16), nullable=False),
        sa.Column(
            "case_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("definition_json", sa.JSON(), nullable=False),
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
    op.create_index("ix_plc_test_suites_created_at", "plc_test_suites", ["created_at"])
    op.create_index(
        "ix_plc_test_suites_source_format", "plc_test_suites", ["source_format"]
    )

    op.add_column(
        "jobs", sa.Column("plc_suite_id", sa.String(length=64), nullable=True)
    )
    op.create_index(
        "ix_jobs_plc_suite_status_created_at",
        "jobs",
        ["plc_suite_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_plc_suite_status_created_at", table_name="jobs")
    op.drop_column("jobs", "plc_suite_id")

    op.drop_index("ix_plc_test_suites_source_format", table_name="plc_test_suites")
    op.drop_index("ix_plc_test_suites_created_at", table_name="plc_test_suites")
    op.drop_table("plc_test_suites")
