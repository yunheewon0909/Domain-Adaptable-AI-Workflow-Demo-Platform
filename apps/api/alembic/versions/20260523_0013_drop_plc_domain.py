"""drop PLC domain tables and jobs.plc_suite_id column

Revision ID: 20260523_0013
Revises: 20260523_0012
Create Date: 2026-05-23 18:00:00

The PLC test-automation slice was a parallel domain to the QLoRA+RAG core.
The Mac-native scope is now exclusively QLoRA fine-tuning + RAG, so the PLC
ORM, runners, routers, and tables are removed.

Drop order respects FK dependencies (children first, then parents).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "20260523_0013"
down_revision: Union[str, Sequence[str], None] = "20260523_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PLC_TABLES_IN_DROP_ORDER = (
    "plc_test_run_io_logs",
    "plc_test_run_items",
    "plc_test_runs",
    "plc_llm_suggestions",
    "plc_testcases",
    "plc_execution_profiles",
    "plc_targets",
    "plc_test_suites",
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector_module = __import__("sqlalchemy", fromlist=["inspect"])
    inspector = inspector_module.inspect(bind)

    for table_name in PLC_TABLES_IN_DROP_ORDER:
        if inspector.has_table(table_name):
            op.drop_table(table_name)

    # Drop the dedicated PLC suite index + column on the shared `jobs` table.
    if inspector.has_table("jobs"):
        existing_indexes = {
            idx["name"]
            for idx in inspector.get_indexes("jobs")
            if idx.get("name")
        }
        if "ix_jobs_plc_suite_status_created_at" in existing_indexes:
            op.drop_index("ix_jobs_plc_suite_status_created_at", table_name="jobs")
        existing_columns = {col["name"] for col in inspector.get_columns("jobs")}
        if "plc_suite_id" in existing_columns:
            op.drop_column("jobs", "plc_suite_id")


def downgrade() -> None:
    # No-op: PLC slice is intentionally retired. Restoring would require
    # reintroducing all dropped table DDL, which we no longer maintain.
    pass
