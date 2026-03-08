from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_alembic_upgrade_adds_datasets_and_workflow_job_fields(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "migration-phase1.db"
    monkeypatch.setenv("API_DATABASE_URL", f"sqlite+pysqlite:///{db_path}")

    config = Config("apps/api/alembic.ini")
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    inspector = inspect(engine)

    assert "datasets" in inspector.get_table_names()
    job_columns = {column["name"] for column in inspector.get_columns("jobs")}
    assert {"workflow_key", "dataset_key"}.issubset(job_columns)

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
