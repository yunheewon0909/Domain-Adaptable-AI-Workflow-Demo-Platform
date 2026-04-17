from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from random import random
import subprocess
from threading import Event, Thread
from time import sleep
from typing import Any, Callable

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

SUPPORTED_JOB_TYPES = (
    "rag_reindex",
    "rag_reindex_incremental",
    "ollama_warmup",
    "rag_verify_index",
    "workflow_run",
    "ft_train_model",
    "plc_test_run",
)

RUNNER_MODULE_BY_JOB_TYPE = {
    "rag_reindex": "api.services.rag.reindex_job_runner",
    "rag_reindex_incremental": "api.services.rag.incremental_reindex_job_runner",
    "ollama_warmup": "api.services.rag.warmup_job_runner",
    "rag_verify_index": "api.services.rag.verify_index_job_runner",
    "workflow_run": "api.services.workflows.job_runner",
    "ft_train_model": "api.services.model_registry.job_runner",
    "plc_test_run": "api.services.plc.job_runner",
}


def _get_database_url() -> str:
    return os.getenv(
        "WORKER_DATABASE_URL",
        "postgresql+psycopg://postgres:postgres@localhost:5432/industrial_ai",
    )


def _get_worker_id() -> str:
    return os.getenv("WORKER_ID", "worker-1")


def _get_heartbeat_seconds() -> int:
    value = os.getenv("WORKER_HEARTBEAT_SECONDS", "30")
    return max(1, int(value))


def _get_poll_seconds() -> int:
    value = os.getenv("WORKER_POLL_SECONDS", "5")
    return max(1, int(value))


def _get_default_max_attempts() -> int:
    value = os.getenv("JOB_MAX_ATTEMPTS", "3")
    return max(1, int(value))


def _get_retry_base_seconds() -> float:
    value = os.getenv("WORKER_DB_RETRY_BASE_SECONDS", "1")
    return max(0.1, float(value))


def _get_retry_max_seconds() -> float:
    value = os.getenv("WORKER_DB_RETRY_MAX_SECONDS", "30")
    return max(0.5, float(value))


def _create_engine() -> Engine:
    return create_engine(
        _get_database_url(),
        pool_pre_ping=True,
    )


def _upsert_heartbeat(engine: Engine, worker_id: str, now: datetime) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO worker_heartbeats (worker_id, last_heartbeat, updated_at)
                VALUES (:worker_id, :last_heartbeat, CURRENT_TIMESTAMP)
                ON CONFLICT(worker_id) DO UPDATE
                SET last_heartbeat = EXCLUDED.last_heartbeat,
                    updated_at = CURRENT_TIMESTAMP
                """
            ),
            {
                "worker_id": worker_id,
                "last_heartbeat": now,
            },
        )


def send_heartbeat_once(engine: Engine, worker_id: str) -> None:
    now = datetime.now(timezone.utc)
    base = _get_retry_base_seconds()
    max_delay = _get_retry_max_seconds()
    delay = base
    attempt = 1

    while True:
        try:
            _upsert_heartbeat(engine, worker_id, now)
            print(
                f"[worker] heartbeat upserted worker_id={worker_id} at={now.isoformat()}",
                flush=True,
            )
            return
        except Exception as exc:
            print(
                f"[worker] heartbeat upsert failed attempt={attempt} error={exc!r}; retrying in {delay:.1f}s",
                flush=True,
            )
            sleep(delay + random() * 0.2 * delay)
            delay = min(delay * 2, max_delay)
            attempt += 1


def _heartbeat_loop(
    engine: Engine, worker_id: str, interval_seconds: int, stop_event: Event
) -> None:
    while not stop_event.is_set():
        send_heartbeat_once(engine, worker_id)
        stop_event.wait(interval_seconds)


def _normalize_payload(payload_json: Any) -> dict[str, Any] | None:
    if isinstance(payload_json, dict):
        return payload_json
    if isinstance(payload_json, str) and payload_json.strip():
        try:
            parsed = json.loads(payload_json)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def _coerce_job_id(job_id: Any) -> int | str:
    if isinstance(job_id, bool):
        return str(job_id)
    if isinstance(job_id, int):
        return job_id
    if isinstance(job_id, str):
        normalized = job_id.strip()
        if normalized.isdigit():
            return int(normalized)
        return normalized
    return str(job_id)


def _build_job_type_params(job_types: tuple[str, ...]) -> tuple[str, dict[str, str]]:
    placeholders = ", ".join(f":job_type_{index}" for index, _ in enumerate(job_types))
    params = {f"job_type_{index}": job_type for index, job_type in enumerate(job_types)}
    return placeholders, params


def _claim_next_job(
    engine: Engine, *, job_types: tuple[str, ...]
) -> dict[str, Any] | None:
    if not job_types:
        return None

    placeholders, type_params = _build_job_type_params(job_types)

    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            row = (
                connection.execute(
                    text(
                        """
                    SELECT id, type, payload_json, attempts, max_attempts
                    FROM jobs
                    WHERE status = 'queued' AND type IN ("""
                        + placeholders
                        + """)
                    ORDER BY created_at ASC, id ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                    """
                    ),
                    type_params,
                )
                .mappings()
                .first()
            )
            if row is None:
                return None

            connection.execute(
                text(
                    """
                    UPDATE jobs
                    SET status = 'running',
                        started_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP,
                        finished_at = NULL,
                        error = NULL
                    WHERE CAST(id AS TEXT) = CAST(:job_id AS TEXT)
                    """
                ),
                {"job_id": _coerce_job_id(row["id"])},
            )

            if str(row["type"]) == "ft_train_model":
                _sync_ft_training_job_claimed(connection, _coerce_job_id(row["id"]))
            if str(row["type"]) == "plc_test_run":
                _sync_plc_run_claimed(connection, _coerce_job_id(row["id"]))

            return {
                "id": _coerce_job_id(row["id"]),
                "type": str(row["type"]),
                "payload_json": _normalize_payload(row["payload_json"]),
                "attempts": int(row["attempts"] or 0),
                "max_attempts": int(row["max_attempts"] or _get_default_max_attempts()),
            }

    with engine.begin() as connection:
        row = (
            connection.execute(
                text(
                    """
                SELECT id, type, payload_json, attempts, max_attempts
                FROM jobs
                WHERE status = 'queued' AND type IN ("""
                    + placeholders
                    + """)
                ORDER BY created_at ASC, id ASC
                LIMIT 1
                """
                ),
                type_params,
            )
            .mappings()
            .first()
        )
        if row is None:
            return None

        claimed = connection.execute(
            text(
                """
                UPDATE jobs
                SET status = 'running',
                    started_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP,
                    finished_at = NULL,
                    error = NULL
                WHERE CAST(id AS TEXT) = CAST(:job_id AS TEXT) AND status = 'queued'
                """
            ),
            {"job_id": _coerce_job_id(row["id"])},
        )
        if claimed.rowcount != 1:
            return None

        if str(row["type"]) == "ft_train_model":
            _sync_ft_training_job_claimed(connection, _coerce_job_id(row["id"]))
        if str(row["type"]) == "plc_test_run":
            _sync_plc_run_claimed(connection, _coerce_job_id(row["id"]))

        return {
            "id": _coerce_job_id(row["id"]),
            "type": str(row["type"]),
            "payload_json": _normalize_payload(row["payload_json"]),
            "attempts": int(row["attempts"] or 0),
            "max_attempts": int(row["max_attempts"] or _get_default_max_attempts()),
        }


def _sync_plc_run_claimed(connection, job_id: int | str) -> None:
    connection.execute(
        text(
            """
            UPDATE plc_test_runs
            SET status = 'running',
                started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                queued_count = 0,
                running_count = total_count
            WHERE CAST(id AS TEXT) = CAST(:job_id AS TEXT)
            """
        ),
        {"job_id": job_id},
    )
    connection.execute(
        text(
            """
            UPDATE plc_test_run_items
            SET status = 'running',
                started_at = COALESCE(started_at, CURRENT_TIMESTAMP)
            WHERE CAST(run_id AS TEXT) = CAST(:job_id AS TEXT)
              AND status = 'queued'
            """
        ),
        {"job_id": job_id},
    )


def _sync_ft_training_job_claimed(connection, job_id: int | str) -> None:
    connection.execute(
        text(
            """
            UPDATE ft_training_jobs
            SET status = 'running',
                started_at = COALESCE(started_at, CURRENT_TIMESTAMP)
            WHERE CAST(backing_job_id AS TEXT) = CAST(:job_id AS TEXT)
            """
        ),
        {"job_id": job_id},
    )


def _sync_ft_training_job_status(
    connection, *, job_id: int | str, status: str, error_message: str | None = None
) -> None:
    connection.execute(
        text(
            """
            UPDATE ft_training_jobs
            SET status = CAST(:status AS VARCHAR),
                started_at = CASE
                    WHEN CAST(:status AS VARCHAR) = 'queued' THEN NULL
                    ELSE started_at
                END,
                finished_at = CASE
                    WHEN CAST(:status AS VARCHAR) = 'queued' THEN NULL
                    WHEN CAST(:status AS VARCHAR) IN ('succeeded', 'failed') THEN CURRENT_TIMESTAMP
                    ELSE finished_at
                END,
                log_text = CASE
                    WHEN :error_message IS NOT NULL THEN COALESCE(log_text, '') || CASE WHEN COALESCE(log_text, '') = '' THEN '' ELSE '\n' END || :error_message
                    ELSE log_text
                END
            WHERE CAST(backing_job_id AS TEXT) = CAST(:job_id AS TEXT)
            """
        ),
        {"job_id": job_id, "status": status, "error_message": error_message},
    )


def _sync_plc_run_status(
    connection,
    *,
    job_id: int | str,
    status: str,
    error_message: str | None = None,
) -> None:
    if status == "queued":
        connection.execute(
            text(
                """
                UPDATE plc_test_runs
                SET status = 'queued',
                    started_at = NULL,
                    finished_at = NULL,
                    queued_count = total_count,
                    running_count = 0
                WHERE CAST(id AS TEXT) = CAST(:job_id AS TEXT)
                """
            ),
            {"job_id": job_id},
        )
        connection.execute(
            text(
                """
                UPDATE plc_test_run_items
                SET status = 'queued',
                    started_at = NULL,
                    finished_at = NULL,
                    failure_reason = NULL
                WHERE CAST(run_id AS TEXT) = CAST(:job_id AS TEXT)
                  AND status IN ('queued', 'running', 'error')
                """
            ),
            {"job_id": job_id},
        )
        return

    connection.execute(
        text(
            """
            UPDATE plc_test_runs
            SET status = CAST(:status AS VARCHAR),
                finished_at = CURRENT_TIMESTAMP,
                queued_count = 0,
                running_count = 0
            WHERE CAST(id AS TEXT) = CAST(:job_id AS TEXT)
            """
        ),
        {"job_id": job_id, "status": status},
    )

    if status == "failed":
        connection.execute(
            text(
                """
                UPDATE plc_test_run_items
                SET status = 'error',
                    failure_reason = COALESCE(failure_reason, :error_message),
                    finished_at = CURRENT_TIMESTAMP
                WHERE CAST(run_id AS TEXT) = CAST(:job_id AS TEXT)
                  AND status IN ('queued', 'running')
                """
            ),
            {"job_id": job_id, "error_message": error_message or "PLC run failed"},
        )


def _claim_next_rag_reindex_job(engine: Engine) -> dict[str, Any] | None:
    return _claim_next_job(engine, job_types=("rag_reindex",))


def _build_subprocess_env(api_project_dir: str) -> dict[str, str]:
    env = os.environ.copy()
    keys_to_propagate = [
        "WORKER_API_PROJECT_DIR",
        "API_DATABASE_URL",
        "OLLAMA_BASE_URL",
        "OLLAMA_MODEL",
        "OLLAMA_FALLBACK_MODEL",
        "OLLAMA_EMBED_BASE_URL",
        "OLLAMA_EMBED_MODEL",
        "OLLAMA_TIMEOUT_SECONDS",
        "RAG_SOURCE_DIR",
        "RAG_INDEX_DIR",
        "RAG_DB_PATH",
        "RAG_EXPECTED_EMBED_DIM",
        "RAG_VERIFY_SAMPLE_QUERY",
        "PLC_EXECUTOR_MODE",
        "PLC_CLI_PATH",
        "PLC_CLI_TIMEOUT_SECONDS",
        "TRAINING_DEVICE",
        "TRAINING_ALLOW_CPU",
        "MODEL_ARTIFACT_DIR",
        "FT_MAX_SEQ_LENGTH",
        "FT_DEFAULT_TRAINING_METHOD",
        "FT_TRAINER_BACKEND",
        "FT_TRAINER_MODEL_MAP_JSON",
        "OLLAMA_PUBLISH_ENABLED",
        "OLLAMA_MODEL_NAMESPACE",
    ]
    for key in keys_to_propagate:
        value = os.getenv(key)
        if value is not None:
            env[key] = value

    env["WORKER_API_PROJECT_DIR"] = api_project_dir
    if "API_DATABASE_URL" not in env:
        worker_db_url = os.getenv("WORKER_DATABASE_URL")
        if worker_db_url is not None:
            env["API_DATABASE_URL"] = worker_db_url
    return env


def _run_job_subprocess(
    job_type: str, payload_json: dict[str, Any] | None = None
) -> dict[str, Any]:
    if job_type not in RUNNER_MODULE_BY_JOB_TYPE:
        raise RuntimeError(f"unsupported job type for subprocess runner: {job_type}")

    api_project_dir = os.getenv("WORKER_API_PROJECT_DIR", "/workspace/apps/api")
    workspace_root = str(Path(api_project_dir).resolve().parents[1])
    command = [
        "uv",
        "run",
        "--project",
        api_project_dir,
        "python",
        "-m",
        RUNNER_MODULE_BY_JOB_TYPE[job_type],
    ]
    if payload_json is not None:
        command.extend(["--payload-json", json.dumps(payload_json)])

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        cwd=workspace_root,
        env=_build_subprocess_env(api_project_dir),
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip()
        stderr_first_line = stderr.splitlines()[0] if stderr else "<empty>"
        print(
            (
                f"[worker] {job_type} subprocess failed "
                f"exit={completed.returncode} stderr_first={stderr_first_line}"
            ),
            flush=True,
        )
        raise RuntimeError(
            f"{job_type} subprocess failed (exit={completed.returncode}): {stderr}"
        )

    output = completed.stdout.strip().splitlines()
    if not output:
        raise RuntimeError(f"{job_type} subprocess produced no output")

    try:
        parsed = json.loads(output[-1])
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"{job_type} subprocess returned invalid JSON: {output[-1]}"
        ) from exc

    if not isinstance(parsed, dict):
        raise RuntimeError(f"{job_type} subprocess payload must be an object")
    return parsed


def _run_reindex_subprocess(
    payload_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _run_job_subprocess("rag_reindex", payload_json)


def _mark_job_succeeded(
    engine: Engine,
    job_id: int | str,
    result_json: dict[str, Any],
    *,
    job_type: str,
) -> None:
    with engine.begin() as connection:
        if job_type == "ft_train_model":
            _sync_ft_training_job_status(connection, job_id=job_id, status="succeeded")
        if job_type == "plc_test_run":
            _sync_plc_run_status(connection, job_id=job_id, status="succeeded")
        connection.execute(
            text(
                """
                UPDATE jobs
                SET status = 'succeeded',
                    result_json = :result_json,
                    finished_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP,
                    error = NULL
                WHERE CAST(id AS TEXT) = CAST(:job_id AS TEXT)
                """
            ),
            {"job_id": job_id, "result_json": json.dumps(result_json)},
        )


def _mark_job_failure(
    engine: Engine,
    *,
    job_id: int | str,
    job_type: str,
    attempts: int,
    max_attempts: int,
    error_message: str,
) -> None:
    next_attempts = attempts + 1
    requeue = next_attempts < max_attempts

    with engine.begin() as connection:
        if job_type == "ft_train_model":
            _sync_ft_training_job_status(
                connection,
                job_id=job_id,
                status="queued" if requeue else "failed",
                error_message=error_message,
            )
        if job_type == "plc_test_run":
            _sync_plc_run_status(
                connection,
                job_id=job_id,
                status="queued" if requeue else "failed",
                error_message=error_message,
            )
        connection.execute(
            text(
                """
                UPDATE jobs
                SET status = CAST(:status AS VARCHAR),
                    attempts = :attempts,
                    error = :error,
                    finished_at = CASE WHEN CAST(:status AS VARCHAR) = 'failed' THEN CURRENT_TIMESTAMP ELSE NULL END,
                    started_at = CASE WHEN CAST(:status AS VARCHAR) = 'queued' THEN NULL ELSE started_at END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE CAST(id AS TEXT) = CAST(:job_id AS TEXT)
                """
            ),
            {
                "job_id": job_id,
                "status": "queued" if requeue else "failed",
                "attempts": next_attempts,
                "error": error_message,
            },
        )


def _process_claimed_job(
    engine: Engine,
    job: dict[str, Any],
    *,
    runner: Callable[[dict[str, Any] | None], dict[str, Any]],
) -> None:
    job_id = _coerce_job_id(job["id"])
    job_type = str(job.get("type", "unknown"))
    attempts = int(job.get("attempts", 0))
    max_attempts = int(job.get("max_attempts") or _get_default_max_attempts())
    payload = _normalize_payload(job.get("payload_json"))

    try:
        result_json = runner(payload)
    except Exception as exc:
        _mark_job_failure(
            engine,
            job_id=job_id,
            job_type=job_type,
            attempts=attempts,
            max_attempts=max_attempts,
            error_message=str(exc),
        )
        print(
            (
                f"[worker] job failed job_id={job_id} type={job_type} "
                f"attempts={attempts + 1}/{max_attempts} error={exc}"
            ),
            flush=True,
        )
        return

    _mark_job_succeeded(engine, job_id, result_json, job_type=job_type)
    print(
        f"[worker] job succeeded job_id={job_id} type={job_type} result={result_json}",
        flush=True,
    )


def main() -> None:
    worker_id = _get_worker_id()
    heartbeat_seconds = _get_heartbeat_seconds()
    poll_seconds = _get_poll_seconds()
    engine = _create_engine()

    stop_event = Event()
    heartbeat_thread = Thread(
        target=_heartbeat_loop,
        args=(engine, worker_id, heartbeat_seconds, stop_event),
        daemon=True,
    )
    heartbeat_thread.start()

    while True:
        job = _claim_next_job(engine, job_types=SUPPORTED_JOB_TYPES)
        if job is None:
            sleep(poll_seconds)
            continue

        job_type = str(job.get("type", ""))
        _process_claimed_job(
            engine,
            job,
            runner=lambda payload, *, _job_type=job_type: _run_job_subprocess(
                _job_type, payload
            ),
        )


if __name__ == "__main__":
    main()
