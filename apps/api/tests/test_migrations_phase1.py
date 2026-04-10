from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_alembic_upgrade_adds_datasets_workflow_and_plc_job_fields(
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
