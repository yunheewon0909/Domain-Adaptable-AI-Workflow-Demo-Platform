from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_alembic_upgrade_to_head_keeps_datasets_and_drops_plc(
    monkeypatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "migration-phase1.db"
    monkeypatch.setenv("API_DATABASE_URL", f"sqlite+pysqlite:///{db_path}")

    config = Config("apps/api/alembic.ini")
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    # Datasets registry stays at head; required columns are intact.
    assert "datasets" in table_names
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

    # PLC slice is retired; the head migration must have dropped its tables.
    plc_tables = {
        "plc_test_suites",
        "plc_execution_profiles",
        "plc_testcases",
        "plc_test_runs",
        "plc_test_run_items",
        "plc_test_run_io_logs",
        "plc_targets",
        "plc_llm_suggestions",
    }
    assert plc_tables.isdisjoint(table_names), (
        f"PLC tables should be dropped at head but found: {plc_tables & table_names}"
    )

    # jobs.plc_suite_id is gone too.
    job_columns = {column["name"] for column in inspector.get_columns("jobs")}
    assert "plc_suite_id" not in job_columns
