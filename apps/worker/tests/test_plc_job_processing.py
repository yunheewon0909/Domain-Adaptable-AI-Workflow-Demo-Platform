from sqlalchemy import create_engine, text

from worker.main import (
    RUNNER_MODULE_BY_JOB_TYPE,
    SUPPORTED_JOB_TYPES,
    _claim_next_job,
    _process_claimed_job,
)


def _create_schema(engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE jobs (
                    id VARCHAR(64) PRIMARY KEY,
                    type VARCHAR(32) NOT NULL,
                    workflow_key VARCHAR(64),
                    dataset_key VARCHAR(64),
                    plc_suite_id VARCHAR(64),
                    status VARCHAR(32) NOT NULL,
                    payload_json TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    finished_at TIMESTAMP,
                    error TEXT,
                    result_json TEXT
                )
                """
            )
        )


def test_worker_claims_and_processes_plc_test_run_job(tmp_path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'worker-plc.db'}")
    _create_schema(engine)

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO jobs (id, type, plc_suite_id, status, payload_json, attempts, max_attempts)
                VALUES ('7', 'plc_test_run', 'plc-suite-1', 'queued', '{"suite_id":"plc-suite-1"}', 0, 3)
                """
            )
        )

    assert "plc_test_run" in SUPPORTED_JOB_TYPES
    assert RUNNER_MODULE_BY_JOB_TYPE["plc_test_run"] == "api.services.plc.job_runner"

    job = _claim_next_job(engine, job_types=("plc_test_run",))
    assert job is not None
    _process_claimed_job(
        engine,
        job,
        runner=lambda _: {
            "suite_id": "plc-suite-1",
            "total_count": 1,
            "passed_count": 1,
            "failed_count": 0,
            "error_count": 0,
            "items": [],
        },
    )

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT status, result_json, error FROM jobs WHERE id = '7'")
        ).fetchone()

    assert row is not None
    assert row[0] == "succeeded"
    assert '"suite_id": "plc-suite-1"' in str(row[1])
    assert row[2] is None
