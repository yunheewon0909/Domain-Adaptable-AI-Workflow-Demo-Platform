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
        connection.execute(
            text(
                """
                CREATE TABLE plc_test_runs (
                    id VARCHAR(64) PRIMARY KEY,
                    suite_id VARCHAR(64) NOT NULL,
                    target_key VARCHAR(64) NOT NULL,
                    backing_job_id VARCHAR(64) NOT NULL,
                    status VARCHAR(32) NOT NULL,
                    total_count INTEGER NOT NULL DEFAULT 0,
                    queued_count INTEGER NOT NULL DEFAULT 0,
                    running_count INTEGER NOT NULL DEFAULT 0,
                    passed_count INTEGER NOT NULL DEFAULT 0,
                    failed_count INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    finished_at TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE plc_test_run_items (
                    id VARCHAR(160) PRIMARY KEY,
                    run_id VARCHAR(64) NOT NULL,
                    testcase_id VARCHAR(128) NOT NULL,
                    case_key VARCHAR(128) NOT NULL,
                    instruction_name VARCHAR(255) NOT NULL,
                    status VARCHAR(32) NOT NULL,
                    expected_output_json TEXT,
                    actual_output_json TEXT,
                    validator_result_json TEXT,
                    failure_reason TEXT,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    executor_log TEXT,
                    started_at TIMESTAMP,
                    finished_at TIMESTAMP
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
        connection.execute(
            text(
                """
                INSERT INTO plc_test_runs (
                    id, suite_id, target_key, backing_job_id, status,
                    total_count, queued_count, running_count, passed_count, failed_count, error_count
                )
                VALUES ('7', 'plc-suite-1', 'stub-local', '7', 'queued', 1, 1, 0, 0, 0, 0)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO plc_test_run_items (
                    id, run_id, testcase_id, case_key, instruction_name, status, validator_result_json
                )
                VALUES ('7::ADD_001::result', '7', 'plc-suite-1::ADD_001', 'ADD_001', 'add', 'queued', '{}')
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
        run_row = connection.execute(
            text(
                "SELECT status, queued_count, running_count FROM plc_test_runs WHERE id = '7'"
            )
        ).fetchone()
        item_row = connection.execute(
            text(
                "SELECT status FROM plc_test_run_items WHERE id = '7::ADD_001::result'"
            )
        ).fetchone()

    assert row is not None
    assert row[0] == "succeeded"
    assert '"suite_id": "plc-suite-1"' in str(row[1])
    assert row[2] is None
    assert run_row is not None
    assert run_row[0] == "succeeded"
    assert run_row[1] == 0
    assert run_row[2] == 0
    assert item_row is not None
    assert item_row[0] == "running"


def test_worker_marks_plc_run_failed_after_final_attempt(tmp_path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'worker-plc-fail.db'}")
    _create_schema(engine)

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO jobs (id, type, plc_suite_id, status, payload_json, attempts, max_attempts)
                VALUES ('8', 'plc_test_run', 'plc-suite-1', 'queued', '{"suite_id":"plc-suite-1"}', 0, 1)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO plc_test_runs (
                    id, suite_id, target_key, backing_job_id, status,
                    total_count, queued_count, running_count, passed_count, failed_count, error_count
                )
                VALUES ('8', 'plc-suite-1', 'stub-local', '8', 'queued', 1, 1, 0, 0, 0, 0)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO plc_test_run_items (
                    id, run_id, testcase_id, case_key, instruction_name, status, validator_result_json
                )
                VALUES ('8::ADD_001::result', '8', 'plc-suite-1::ADD_001', 'ADD_001', 'add', 'queued', '{}')
                """
            )
        )

    job = _claim_next_job(engine, job_types=("plc_test_run",))
    assert job is not None
    _process_claimed_job(
        engine,
        job,
        runner=lambda _: (_ for _ in ()).throw(
            RuntimeError("executor transport failed")
        ),
    )

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT status, attempts, error FROM jobs WHERE id = '8'")
        ).fetchone()
        run_row = connection.execute(
            text(
                "SELECT status, queued_count, running_count FROM plc_test_runs WHERE id = '8'"
            )
        ).fetchone()
        item_row = connection.execute(
            text(
                "SELECT status, failure_reason FROM plc_test_run_items WHERE id = '8::ADD_001::result'"
            )
        ).fetchone()

    assert row is not None
    assert row[0] == "failed"
    assert row[1] == 1
    assert "executor transport failed" in str(row[2])
    assert run_row is not None
    assert run_row[0] == "failed"
    assert run_row[1] == 0
    assert run_row[2] == 0
    assert item_row is not None
    assert item_row[0] == "error"
    assert "executor transport failed" in str(item_row[1])
