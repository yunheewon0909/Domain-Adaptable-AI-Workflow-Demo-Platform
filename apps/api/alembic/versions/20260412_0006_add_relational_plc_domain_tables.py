"""add relational plc domain tables

Revision ID: 20260412_0006
Revises: 20260411_0005
Create Date: 2026-04-12 11:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260412_0006"
down_revision: Union[str, Sequence[str], None] = "20260411_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plc_targets",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("executor_mode", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
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
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index("ix_plc_targets_created_at", "plc_targets", ["created_at"])
    op.create_index("ix_plc_targets_is_active", "plc_targets", ["is_active"])

    op.create_table(
        "plc_testcases",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("suite_id", sa.String(length=64), nullable=False),
        sa.Column("testcase_key", sa.String(length=128), nullable=False),
        sa.Column("case_key", sa.String(length=128), nullable=False),
        sa.Column("instruction_name", sa.String(length=255), nullable=False),
        sa.Column("input_type", sa.String(length=64), nullable=False),
        sa.Column("output_type", sa.String(length=64), nullable=False),
        sa.Column("input_vector_json", sa.JSON(), nullable=False),
        sa.Column("expected_output_json", sa.JSON(), nullable=False),
        sa.Column("expected_outputs_json", sa.JSON(), nullable=False),
        sa.Column(
            "expected_outcome",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pass'"),
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags_json", sa.JSON(), nullable=False),
        sa.Column("memory_profile_key", sa.String(length=255), nullable=True),
        sa.Column(
            "timeout_ms", sa.Integer(), nullable=False, server_default=sa.text("3000")
        ),
        sa.Column("source_row_number", sa.Integer(), nullable=False),
        sa.Column("source_case_index", sa.Integer(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
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
        sa.ForeignKeyConstraint(["suite_id"], ["plc_test_suites.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "suite_id", "case_key", name="uq_plc_testcases_suite_case_key"
        ),
    )
    op.create_index("ix_plc_testcases_created_at", "plc_testcases", ["created_at"])
    op.create_index("ix_plc_testcases_input_type", "plc_testcases", ["input_type"])
    op.create_index(
        "ix_plc_testcases_instruction_name", "plc_testcases", ["instruction_name"]
    )
    op.create_index("ix_plc_testcases_is_active", "plc_testcases", ["is_active"])
    op.create_index("ix_plc_testcases_suite_id", "plc_testcases", ["suite_id"])

    op.create_table(
        "plc_test_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("suite_id", sa.String(length=64), nullable=False),
        sa.Column("target_key", sa.String(length=64), nullable=False),
        sa.Column("backing_job_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "total_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "queued_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "running_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "passed_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "failed_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "error_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["backing_job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["suite_id"], ["plc_test_suites.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("backing_job_id", name="uq_plc_test_runs_backing_job_id"),
    )
    op.create_index(
        "ix_plc_test_runs_status_created_at",
        "plc_test_runs",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_plc_test_runs_suite_id_created_at",
        "plc_test_runs",
        ["suite_id", "created_at"],
    )
    op.create_index("ix_plc_test_runs_target_key", "plc_test_runs", ["target_key"])

    op.create_table(
        "plc_test_run_items",
        sa.Column("id", sa.String(length=160), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("testcase_id", sa.String(length=128), nullable=False),
        sa.Column("case_key", sa.String(length=128), nullable=False),
        sa.Column("instruction_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("expected_output_json", sa.JSON(), nullable=False),
        sa.Column("actual_output_json", sa.JSON(), nullable=True),
        sa.Column("validator_result_json", sa.JSON(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "duration_ms", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "executor_log", sa.Text(), nullable=False, server_default=sa.text("''")
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["plc_test_runs.id"]),
        sa.ForeignKeyConstraint(["testcase_id"], ["plc_testcases.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id", "testcase_id", name="uq_plc_test_run_items_run_testcase"
        ),
    )
    op.create_index(
        "ix_plc_test_run_items_case_key", "plc_test_run_items", ["case_key"]
    )
    op.create_index("ix_plc_test_run_items_run_id", "plc_test_run_items", ["run_id"])
    op.create_index("ix_plc_test_run_items_status", "plc_test_run_items", ["status"])
    op.create_index(
        "ix_plc_test_run_items_testcase_id", "plc_test_run_items", ["testcase_id"]
    )

    op.create_table(
        "plc_test_run_io_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_item_id", sa.String(length=160), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("memory_address", sa.String(length=128), nullable=True),
        sa.Column("memory_symbol", sa.String(length=128), nullable=True),
        sa.Column("value_json", sa.JSON(), nullable=True),
        sa.Column("raw_type", sa.String(length=64), nullable=True),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["run_item_id"], ["plc_test_run_items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_plc_test_run_io_logs_direction", "plc_test_run_io_logs", ["direction"]
    )
    op.create_index(
        "ix_plc_test_run_io_logs_run_item_id", "plc_test_run_io_logs", ["run_item_id"]
    )
    op.create_index(
        "ix_plc_test_run_io_logs_run_item_sequence",
        "plc_test_run_io_logs",
        ["run_item_id", "sequence_no"],
    )

    op.bulk_insert(
        sa.table(
            "plc_targets",
            sa.column("key", sa.String(length=64)),
            sa.column("display_name", sa.String(length=255)),
            sa.column("description", sa.Text()),
            sa.column("executor_mode", sa.String(length=32)),
            sa.column("metadata_json", sa.JSON()),
            sa.column("is_active", sa.Boolean()),
        ),
        [
            {
                "key": "stub-local",
                "display_name": "Stub Local",
                "description": "Deterministic in-repo stub executor target for PLC test reviews.",
                "executor_mode": "stub",
                "metadata_json": {},
                "is_active": True,
            }
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_plc_test_run_io_logs_run_item_sequence", table_name="plc_test_run_io_logs"
    )
    op.drop_index(
        "ix_plc_test_run_io_logs_run_item_id", table_name="plc_test_run_io_logs"
    )
    op.drop_index(
        "ix_plc_test_run_io_logs_direction", table_name="plc_test_run_io_logs"
    )
    op.drop_table("plc_test_run_io_logs")

    op.drop_index("ix_plc_test_run_items_testcase_id", table_name="plc_test_run_items")
    op.drop_index("ix_plc_test_run_items_status", table_name="plc_test_run_items")
    op.drop_index("ix_plc_test_run_items_run_id", table_name="plc_test_run_items")
    op.drop_index("ix_plc_test_run_items_case_key", table_name="plc_test_run_items")
    op.drop_table("plc_test_run_items")

    op.drop_index("ix_plc_test_runs_target_key", table_name="plc_test_runs")
    op.drop_index("ix_plc_test_runs_suite_id_created_at", table_name="plc_test_runs")
    op.drop_index("ix_plc_test_runs_status_created_at", table_name="plc_test_runs")
    op.drop_table("plc_test_runs")

    op.drop_index("ix_plc_testcases_suite_id", table_name="plc_testcases")
    op.drop_index("ix_plc_testcases_is_active", table_name="plc_testcases")
    op.drop_index("ix_plc_testcases_instruction_name", table_name="plc_testcases")
    op.drop_index("ix_plc_testcases_input_type", table_name="plc_testcases")
    op.drop_index("ix_plc_testcases_created_at", table_name="plc_testcases")
    op.drop_table("plc_testcases")

    op.drop_index("ix_plc_targets_is_active", table_name="plc_targets")
    op.drop_index("ix_plc_targets_created_at", table_name="plc_targets")
    op.drop_table("plc_targets")
