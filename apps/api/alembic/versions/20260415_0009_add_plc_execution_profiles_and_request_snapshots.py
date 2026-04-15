"""add plc execution profiles and request snapshots

Revision ID: 20260415_0009
Revises: 20260412_0008
Create Date: 2026-04-15 15:30:00
"""

from __future__ import annotations

import json
import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260415_0009"
down_revision: Union[str, Sequence[str], None] = "20260412_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _normalize_profile_fragment(value: str | None) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return normalized or "default"


def _derive_profile_key(row: dict[str, object]) -> str:
    memory_profile_key = row.get("memory_profile_key")
    if memory_profile_key:
        return _normalize_profile_fragment(str(memory_profile_key))
    return "--".join(
        [
            _normalize_profile_fragment(str(row.get("instruction_name") or "")),
            _normalize_profile_fragment(str(row.get("input_type") or "")),
            _normalize_profile_fragment(str(row.get("output_type") or "")),
        ]
    )


def upgrade() -> None:
    op.create_table(
        "plc_execution_profiles",
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("memory_profile_key", sa.String(length=255), nullable=True),
        sa.Column("instruction_name", sa.String(length=255), nullable=False),
        sa.Column("input_type", sa.String(length=64), nullable=False),
        sa.Column("output_type", sa.String(length=64), nullable=False),
        sa.Column("profile_version", sa.String(length=64), nullable=True),
        sa.Column("timeout_policy_json", sa.JSON(), nullable=False),
        sa.Column("setup_requirements_json", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("address_contract_json", sa.JSON(), nullable=False),
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
    op.create_index(
        "ix_plc_execution_profiles_instruction_name",
        "plc_execution_profiles",
        ["instruction_name"],
    )
    op.create_index(
        "ix_plc_execution_profiles_is_active",
        "plc_execution_profiles",
        ["is_active"],
    )
    op.create_index(
        "ix_plc_execution_profiles_memory_profile_key",
        "plc_execution_profiles",
        ["memory_profile_key"],
    )

    with op.batch_alter_table("plc_testcases") as batch_op:
        batch_op.add_column(
            sa.Column("execution_profile_key", sa.String(length=255), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_plc_testcases_execution_profile_key",
            "plc_execution_profiles",
            ["execution_profile_key"],
            ["key"],
        )

    with op.batch_alter_table("plc_test_runs") as batch_op:
        batch_op.add_column(
            sa.Column("request_schema_version", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column("executor_mode", sa.String(length=32), nullable=True)
        )
        batch_op.add_column(
            sa.Column("validator_version", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(sa.Column("target_snapshot_json", sa.JSON(), nullable=True))

    with op.batch_alter_table("plc_test_run_items") as batch_op:
        batch_op.add_column(
            sa.Column("input_type", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column("output_type", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "timeout_ms",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("3000"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "expected_outcome",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'pass'"),
            )
        )
        batch_op.add_column(
            sa.Column("memory_profile_key", sa.String(length=255), nullable=True)
        )
        batch_op.add_column(
            sa.Column("execution_profile_key", sa.String(length=255), nullable=True)
        )
        batch_op.add_column(sa.Column("inputs_json", sa.JSON(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "request_context_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )

    connection = op.get_bind()
    testcase_rows = [
        dict(row._mapping)
        for row in connection.execute(
            sa.text(
                """
                SELECT id, instruction_name, input_type, output_type, memory_profile_key,
                       timeout_ms, description
                FROM plc_testcases
                """
            )
        )
    ]
    profile_rows_by_key: dict[str, dict[str, object]] = {}
    for row in testcase_rows:
        profile_key = _derive_profile_key(row)
        profile_rows_by_key.setdefault(
            profile_key,
            {
                "key": profile_key,
                "memory_profile_key": row.get("memory_profile_key"),
                "instruction_name": row.get("instruction_name"),
                "input_type": row.get("input_type"),
                "output_type": row.get("output_type"),
                "profile_version": None,
                "timeout_policy_json": {
                    "default_timeout_ms": int(row.get("timeout_ms") or 3000)
                },
                "setup_requirements_json": {
                    "requires_setup": False,
                    "requires_reset": False,
                },
                "notes": row.get("description")
                or f"Prepared execution profile scaffold for {row.get('instruction_name')}.",
                "address_contract_json": {
                    "placeholder": True,
                    "status": "unbound",
                    "adapter_contract": "future-plc-address-contract",
                },
                "is_active": True,
            },
        )
        connection.execute(
            sa.text(
                "UPDATE plc_testcases SET execution_profile_key = :profile_key WHERE id = :id"
            ),
            {"profile_key": profile_key, "id": row["id"]},
        )

    if profile_rows_by_key:
        op.bulk_insert(
            sa.table(
                "plc_execution_profiles",
                sa.column("key", sa.String(length=255)),
                sa.column("memory_profile_key", sa.String(length=255)),
                sa.column("instruction_name", sa.String(length=255)),
                sa.column("input_type", sa.String(length=64)),
                sa.column("output_type", sa.String(length=64)),
                sa.column("profile_version", sa.String(length=64)),
                sa.column("timeout_policy_json", sa.JSON()),
                sa.column("setup_requirements_json", sa.JSON()),
                sa.column("notes", sa.Text()),
                sa.column("address_contract_json", sa.JSON()),
                sa.column("is_active", sa.Boolean()),
            ),
            list(profile_rows_by_key.values()),
        )

    run_rows = [
        dict(row._mapping)
        for row in connection.execute(
            sa.text(
                """
                SELECT runs.id, runs.target_key, targets.display_name, targets.executor_mode,
                       targets.metadata_json
                FROM plc_test_runs AS runs
                LEFT JOIN plc_targets AS targets ON targets.key = runs.target_key
                """
            )
        )
    ]
    for row in run_rows:
        metadata_json = row.get("metadata_json")
        if isinstance(metadata_json, str):
            metadata_json = json.loads(metadata_json)
        connection.execute(
            sa.text(
                """
                UPDATE plc_test_runs
                SET request_schema_version = :request_schema_version,
                    executor_mode = :executor_mode,
                    validator_version = :validator_version,
                    target_snapshot_json = :target_snapshot_json
                WHERE id = :id
                """
            ),
            {
                "id": row["id"],
                "request_schema_version": "plc-execution-request.v2",
                "executor_mode": row.get("executor_mode") or "stub",
                "validator_version": "exact-match.v1",
                "target_snapshot_json": {
                    "key": row.get("target_key"),
                    "display_name": row.get("display_name") or row.get("target_key"),
                    "executor_mode": row.get("executor_mode") or "stub",
                    "metadata_json": metadata_json or {},
                },
            },
        )

    run_item_rows = [
        dict(row._mapping)
        for row in connection.execute(
            sa.text(
                """
                SELECT items.id, items.case_key, items.run_id, items.testcase_id,
                       cases.input_type, cases.output_type, cases.timeout_ms,
                       cases.expected_outcome, cases.memory_profile_key,
                       cases.execution_profile_key, cases.input_vector_json,
                       cases.description, cases.tags_json, cases.source_row_number,
                       cases.source_case_index, runs.suite_id, suites.title AS suite_title,
                       runs.target_snapshot_json
                FROM plc_test_run_items AS items
                JOIN plc_testcases AS cases ON cases.id = items.testcase_id
                JOIN plc_test_runs AS runs ON runs.id = items.run_id
                JOIN plc_test_suites AS suites ON suites.id = runs.suite_id
                """
            )
        )
    ]
    for row in run_item_rows:
        target_snapshot_json = row.get("target_snapshot_json")
        if isinstance(target_snapshot_json, str):
            target_snapshot_json = json.loads(target_snapshot_json)
        tags_json = row.get("tags_json")
        if isinstance(tags_json, str):
            tags_json = json.loads(tags_json)
        connection.execute(
            sa.text(
                """
                UPDATE plc_test_run_items
                SET input_type = :input_type,
                    output_type = :output_type,
                    timeout_ms = :timeout_ms,
                    expected_outcome = :expected_outcome,
                    memory_profile_key = :memory_profile_key,
                    execution_profile_key = :execution_profile_key,
                    inputs_json = :inputs_json,
                    request_context_json = :request_context_json
                WHERE id = :id
                """
            ),
            {
                "id": row["id"],
                "input_type": row.get("input_type"),
                "output_type": row.get("output_type"),
                "timeout_ms": row.get("timeout_ms") or 3000,
                "expected_outcome": row.get("expected_outcome") or "pass",
                "memory_profile_key": row.get("memory_profile_key"),
                "execution_profile_key": row.get("execution_profile_key"),
                "inputs_json": row.get("input_vector_json"),
                "request_context_json": {
                    "run_context": {
                        "run_id": row.get("run_id"),
                        "suite_id": row.get("suite_id"),
                        "suite_title": row.get("suite_title"),
                    },
                    "testcase_context": {
                        "case_key": row.get("case_key"),
                        "description": row.get("description"),
                        "tags": tags_json or [],
                        "source_row_number": row.get("source_row_number"),
                        "source_case_index": row.get("source_case_index"),
                    },
                    "target_context": target_snapshot_json,
                },
            },
        )


def downgrade() -> None:
    with op.batch_alter_table("plc_test_run_items") as batch_op:
        batch_op.drop_column("request_context_json")
        batch_op.drop_column("inputs_json")
        batch_op.drop_column("execution_profile_key")
        batch_op.drop_column("memory_profile_key")
        batch_op.drop_column("expected_outcome")
        batch_op.drop_column("timeout_ms")
        batch_op.drop_column("output_type")
        batch_op.drop_column("input_type")

    with op.batch_alter_table("plc_test_runs") as batch_op:
        batch_op.drop_column("target_snapshot_json")
        batch_op.drop_column("validator_version")
        batch_op.drop_column("executor_mode")
        batch_op.drop_column("request_schema_version")

    with op.batch_alter_table("plc_testcases") as batch_op:
        batch_op.drop_constraint(
            "fk_plc_testcases_execution_profile_key", type_="foreignkey"
        )
        batch_op.drop_column("execution_profile_key")

    op.drop_index(
        "ix_plc_execution_profiles_memory_profile_key",
        table_name="plc_execution_profiles",
    )
    op.drop_index(
        "ix_plc_execution_profiles_is_active",
        table_name="plc_execution_profiles",
    )
    op.drop_index(
        "ix_plc_execution_profiles_instruction_name",
        table_name="plc_execution_profiles",
    )
    op.drop_table("plc_execution_profiles")
