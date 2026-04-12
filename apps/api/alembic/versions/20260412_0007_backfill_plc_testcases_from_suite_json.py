"""backfill plc testcase masters from suite json

Revision ID: 20260412_0007
Revises: 20260412_0006
Create Date: 2026-04-12 13:10:00
"""

from __future__ import annotations

import json
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260412_0007"
down_revision: Union[str, Sequence[str], None] = "20260412_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _coerce_definition_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    return {}


def upgrade() -> None:
    connection = op.get_bind()
    suites = (
        connection.execute(sa.text("SELECT id, definition_json FROM plc_test_suites"))
        .mappings()
        .all()
    )
    existing_case_ids = set(
        connection.execute(sa.text("SELECT id FROM plc_testcases")).scalars().all()
    )

    testcase_table = sa.table(
        "plc_testcases",
        sa.column("id", sa.String(length=128)),
        sa.column("suite_id", sa.String(length=64)),
        sa.column("testcase_key", sa.String(length=128)),
        sa.column("case_key", sa.String(length=128)),
        sa.column("instruction_name", sa.String(length=255)),
        sa.column("input_type", sa.String(length=64)),
        sa.column("output_type", sa.String(length=64)),
        sa.column("input_vector_json", sa.JSON()),
        sa.column("expected_output_json", sa.JSON()),
        sa.column("expected_outputs_json", sa.JSON()),
        sa.column("expected_outcome", sa.String(length=16)),
        sa.column("description", sa.Text()),
        sa.column("tags_json", sa.JSON()),
        sa.column("memory_profile_key", sa.String(length=255)),
        sa.column("timeout_ms", sa.Integer()),
        sa.column("source_row_number", sa.Integer()),
        sa.column("source_case_index", sa.Integer()),
        sa.column("is_active", sa.Boolean()),
    )

    rows_to_insert: list[dict[str, Any]] = []
    for suite in suites:
        definition = _coerce_definition_json(suite["definition_json"])
        cases = definition.get("cases")
        if not isinstance(cases, list):
            continue
        for case in cases:
            if not isinstance(case, dict):
                continue
            case_id = str(case.get("id", "")).strip()
            if not case_id or case_id in existing_case_ids:
                continue
            rows_to_insert.append(
                {
                    "id": case_id,
                    "suite_id": suite["id"],
                    "testcase_key": case_id,
                    "case_key": str(case.get("case_key", "")).strip(),
                    "instruction_name": str(case.get("instruction_name", "")).strip(),
                    "input_type": str(case.get("input_type", "")).strip(),
                    "output_type": str(case.get("output_type", "")).strip(),
                    "input_vector_json": case.get("input_vector_json") or [],
                    "expected_output_json": case.get("expected_output_json"),
                    "expected_outputs_json": case.get("expected_outputs_json") or [],
                    "expected_outcome": (
                        "fail" if case.get("expected_outcome") == "fail" else "pass"
                    ),
                    "description": case.get("description"),
                    "tags_json": case.get("tags") or [],
                    "memory_profile_key": case.get("memory_profile_key"),
                    "timeout_ms": int(case.get("timeout_ms", 3000) or 3000),
                    "source_row_number": int(case.get("source_row_number", 0) or 0),
                    "source_case_index": int(case.get("source_case_index", 0) or 0),
                    "is_active": True,
                }
            )
            existing_case_ids.add(case_id)

    if rows_to_insert:
        op.bulk_insert(testcase_table, rows_to_insert)


def downgrade() -> None:
    # data backfill only; relational tables remain in place on downgrade to 0006
    pass
