from pathlib import Path

from alembic import command
from alembic.config import Config
import json

from sqlalchemy import create_engine, inspect, text


def test_alembic_upgrade_adds_datasets_workflow_and_plc_domain_tables(
    monkeypatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "migration-phase1.db"
    monkeypatch.setenv("API_DATABASE_URL", f"sqlite+pysqlite:///{db_path}")

    config = Config("apps/api/alembic.ini")
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    inspector = inspect(engine)

    assert "datasets" in inspector.get_table_names()
    assert "plc_test_suites" in inspector.get_table_names()
    assert "plc_execution_profiles" in inspector.get_table_names()
    assert "plc_testcases" in inspector.get_table_names()
    assert "plc_test_runs" in inspector.get_table_names()
    assert "plc_test_run_items" in inspector.get_table_names()
    assert "plc_test_run_io_logs" in inspector.get_table_names()
    assert "plc_targets" in inspector.get_table_names()
    assert "plc_llm_suggestions" in inspector.get_table_names()
    job_columns = {column["name"] for column in inspector.get_columns("jobs")}
    assert {"workflow_key", "dataset_key", "plc_suite_id"}.issubset(job_columns)

    dataset_columns = {column["name"] for column in inspector.get_columns("datasets")}
    assert {
        "key",
        "title",
        "domain_type",
        "profile_key",
        "source_dir",
        "index_dir",
        "db_path",
        "is_active",
    }.issubset(dataset_columns)

    plc_suite_columns = {
        column["name"] for column in inspector.get_columns("plc_test_suites")
    }
    assert {
        "id",
        "title",
        "source_filename",
        "source_format",
        "case_count",
        "definition_json",
    }.issubset(plc_suite_columns)

    plc_execution_profile_columns = {
        column["name"] for column in inspector.get_columns("plc_execution_profiles")
    }
    assert {
        "key",
        "memory_profile_key",
        "instruction_name",
        "input_type",
        "output_type",
        "timeout_policy_json",
        "setup_requirements_json",
        "address_contract_json",
    }.issubset(plc_execution_profile_columns)

    plc_testcase_columns = {
        column["name"] for column in inspector.get_columns("plc_testcases")
    }
    assert {
        "id",
        "suite_id",
        "testcase_key",
        "case_key",
        "instruction_name",
        "input_vector_json",
        "expected_output_json",
        "expected_outputs_json",
        "tags_json",
        "execution_profile_key",
        "is_active",
    }.issubset(plc_testcase_columns)

    plc_run_columns = {
        column["name"] for column in inspector.get_columns("plc_test_runs")
    }
    assert {
        "id",
        "suite_id",
        "target_key",
        "backing_job_id",
        "request_schema_version",
        "executor_mode",
        "validator_version",
        "target_snapshot_json",
        "status",
        "total_count",
        "queued_count",
        "running_count",
        "passed_count",
        "failed_count",
        "error_count",
    }.issubset(plc_run_columns)

    plc_run_item_columns = {
        column["name"] for column in inspector.get_columns("plc_test_run_items")
    }
    assert {
        "id",
        "run_id",
        "testcase_id",
        "case_key",
        "input_type",
        "output_type",
        "timeout_ms",
        "expected_outcome",
        "memory_profile_key",
        "execution_profile_key",
        "inputs_json",
        "request_context_json",
        "status",
        "validator_result_json",
        "executor_log",
    }.issubset(plc_run_item_columns)

    plc_io_log_columns = {
        column["name"] for column in inspector.get_columns("plc_test_run_io_logs")
    }
    assert {
        "id",
        "run_item_id",
        "direction",
        "value_json",
        "sequence_no",
    }.issubset(plc_io_log_columns)

    plc_target_columns = {
        column["name"] for column in inspector.get_columns("plc_targets")
    }
    assert {
        "key",
        "display_name",
        "executor_mode",
        "metadata_json",
        "is_active",
    }.issubset(plc_target_columns)

    plc_llm_suggestion_columns = {
        column["name"] for column in inspector.get_columns("plc_llm_suggestions")
    }
    assert {
        "id",
        "suite_id",
        "testcase_id",
        "suggestion_type",
        "source_payload_json",
        "suggestion_payload_json",
        "status",
        "reviewed_at",
    }.issubset(plc_llm_suggestion_columns)


def test_alembic_upgrade_backfills_plc_testcases_from_legacy_suite_json(
    monkeypatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "migration-phase1-backfill.db"
    monkeypatch.setenv("API_DATABASE_URL", f"sqlite+pysqlite:///{db_path}")

    config = Config("apps/api/alembic.ini")
    command.upgrade(config, "20260411_0005")

    engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO plc_test_suites (
                    id, title, source_filename, source_format, case_count, definition_json
                ) VALUES (
                    :id, :title, :source_filename, :source_format, :case_count, :definition_json
                )
                """
            ),
            {
                "id": "plc-suite-legacy",
                "title": "Legacy Suite",
                "source_filename": "legacy.csv",
                "source_format": "csv",
                "case_count": 1,
                "definition_json": json.dumps(
                    {
                        "schema_version": "plc-suite.v1",
                        "warnings": [],
                        "cases": [
                            {
                                "id": "plc-suite-legacy::ADD_001",
                                "case_key": "ADD_001",
                                "instruction_name": "add",
                                "input_type": "LWORD",
                                "output_type": "LWORD",
                                "input_vector_json": [1, 1],
                                "expected_output_json": 2,
                                "expected_outputs_json": [2],
                                "memory_profile_key": "legacy_profile",
                                "description": "legacy case",
                                "tags": ["legacy"],
                                "timeout_ms": 3000,
                                "source_row_number": 2,
                                "source_case_index": 0,
                                "expected_outcome": "pass",
                            }
                        ],
                    }
                ),
            },
        )

    command.upgrade(config, "head")
    inspector = inspect(engine)
    assert "plc_testcases" in inspector.get_table_names()

    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT id, suite_id, case_key FROM plc_testcases WHERE id = 'plc-suite-legacy::ADD_001'"
            )
        ).fetchone()

    assert row is not None
    assert row[0] == "plc-suite-legacy::ADD_001"
    assert row[1] == "plc-suite-legacy"
    assert row[2] == "ADD_001"
