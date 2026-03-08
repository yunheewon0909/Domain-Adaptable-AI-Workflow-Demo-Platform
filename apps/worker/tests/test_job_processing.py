from sqlalchemy import create_engine, text

from worker.main import (
    RUNNER_MODULE_BY_JOB_TYPE,
    SUPPORTED_JOB_TYPES,
    _claim_next_job,
    _claim_next_rag_reindex_job,
    _coerce_job_id,
    _process_claimed_job,
    _run_job_subprocess,
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


def test_coerce_job_id_converts_numeric_string_to_int() -> None:
    assert _coerce_job_id("42") == 42
    assert _coerce_job_id(7) == 7


def test_worker_claim_and_execute_success(tmp_path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'worker-success.db'}")
    _create_schema(engine)

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO jobs (id, type, status, payload_json, attempts, max_attempts)
                VALUES ('1', 'rag_reindex', 'queued', '{"source":"test"}', 0, 3)
                """
            )
        )

    job = _claim_next_rag_reindex_job(engine)
    assert job is not None
    assert job["id"] == 1

    _process_claimed_job(engine, job, runner=lambda _: {"chunks": 12, "duration_ms": 30})

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT status, attempts, result_json, error FROM jobs WHERE id = '1'")
        ).fetchone()

    assert row is not None
    assert row[0] == "succeeded"
    assert row[1] == 0
    assert '"chunks": 12' in str(row[2])
    assert row[3] is None


def test_worker_retries_then_fails_after_max_attempts(tmp_path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'worker-fail.db'}")
    _create_schema(engine)

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO jobs (id, type, status, attempts, max_attempts)
                VALUES ('2', 'rag_reindex', 'queued', 0, 2)
                """
            )
        )

    job = _claim_next_rag_reindex_job(engine)
    assert job is not None
    _process_claimed_job(engine, job, runner=lambda _: (_ for _ in ()).throw(RuntimeError("boom-1")))

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT status, attempts, error FROM jobs WHERE id = '2'")
        ).fetchone()

    assert row is not None
    assert row[0] == "queued"
    assert row[1] == 1
    assert "boom-1" in str(row[2])

    job = _claim_next_rag_reindex_job(engine)
    assert job is not None
    _process_claimed_job(engine, job, runner=lambda _: (_ for _ in ()).throw(RuntimeError("boom-2")))

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT status, attempts, error FROM jobs WHERE id = '2'")
        ).fetchone()

    assert row is not None
    assert row[0] == "failed"
    assert row[1] == 2
    assert "boom-2" in str(row[2])


def test_worker_claims_and_processes_warmup_job(tmp_path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'worker-warmup.db'}")
    _create_schema(engine)

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO jobs (id, type, status, payload_json, attempts, max_attempts)
                VALUES ('3', 'ollama_warmup', 'queued', '{"requested_by":"test"}', 0, 3)
                """
            )
        )

    job = _claim_next_job(engine, job_types=("ollama_warmup",))
    assert job is not None
    assert job["type"] == "ollama_warmup"
    _process_claimed_job(
        engine,
        job,
        runner=lambda _: {
            "embed_ok": True,
            "chat_ok": True,
            "embed_latency_ms": 11,
            "chat_latency_ms": 13,
        },
    )

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT status, attempts, result_json, error FROM jobs WHERE id = '3'")
        ).fetchone()

    assert row is not None
    assert row[0] == "succeeded"
    assert row[1] == 0
    assert '"embed_ok": true' in str(row[2]).lower()
    assert row[3] is None


def test_worker_retries_verify_job_and_marks_failed(tmp_path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'worker-verify-fail.db'}")
    _create_schema(engine)

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO jobs (id, type, status, attempts, max_attempts)
                VALUES ('4', 'rag_verify_index', 'queued', 0, 1)
                """
            )
        )

    job = _claim_next_job(engine, job_types=("rag_verify_index",))
    assert job is not None
    assert job["type"] == "rag_verify_index"
    _process_claimed_job(engine, job, runner=lambda _: (_ for _ in ()).throw(RuntimeError("verify-failed")))

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT status, attempts, error FROM jobs WHERE id = '4'")
        ).fetchone()

    assert row is not None
    assert row[0] == "failed"
    assert row[1] == 1
    assert "verify-failed" in str(row[2])


def test_worker_claims_and_processes_incremental_job(tmp_path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'worker-incremental.db'}")
    _create_schema(engine)

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO jobs (id, type, status, payload_json, attempts, max_attempts)
                VALUES ('5', 'rag_reindex_incremental', 'queued', '{"requested_by":"test"}', 0, 3)
                """
            )
        )

    job = _claim_next_job(engine, job_types=("rag_reindex_incremental",))
    assert job is not None
    assert job["type"] == "rag_reindex_incremental"
    _process_claimed_job(engine, job, runner=lambda _: {"mode": "incremental", "updated": 1})

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT status, attempts, result_json, error FROM jobs WHERE id = '5'")
        ).fetchone()

    assert row is not None
    assert row[0] == "succeeded"
    assert row[1] == 0
    assert '"mode": "incremental"' in str(row[2])
    assert row[3] is None


def test_worker_claims_and_processes_workflow_run_job_with_evidence(tmp_path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'worker-workflow.db'}")
    _create_schema(engine)

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO jobs (id, type, workflow_key, dataset_key, status, payload_json, attempts, max_attempts)
                VALUES (:id, :type, :workflow_key, :dataset_key, :status, :payload_json, :attempts, :max_attempts)
                """
            ),
            {
                "id": "6",
                "type": "workflow_run",
                "workflow_key": "briefing",
                "dataset_key": "enterprise_docs",
                "status": "queued",
                "payload_json": '{"workflow_key":"briefing","dataset_key":"enterprise_docs","prompt":"make a briefing","k":4}',
                "attempts": 0,
                "max_attempts": 3,
            },
        )

    assert "workflow_run" in SUPPORTED_JOB_TYPES
    assert RUNNER_MODULE_BY_JOB_TYPE["workflow_run"] == "api.services.workflows.job_runner"

    job = _claim_next_job(engine, job_types=("workflow_run",))
    assert job is not None
    assert job["type"] == "workflow_run"
    _process_claimed_job(
        engine,
        job,
        runner=lambda payload: {
            "summary": "Demo-ready briefing",
            "key_points": [payload["prompt"]],
            "evidence": [
                {
                    "chunk_id": "c-1",
                    "source_path": "pilot_notes.md",
                    "title": "Pilot Notes",
                    "text": "supporting evidence",
                    "score": 0.91,
                }
            ],
        },
    )

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT status, result_json, error FROM jobs WHERE id = '6'")
        ).fetchone()

    assert row is not None
    assert row[0] == "succeeded"
    assert '"evidence":' in str(row[1])
    assert '"chunk_id": "c-1"' in str(row[1])
    assert row[2] is None


def test_run_job_subprocess_propagates_ollama_and_rag_env(monkeypatch) -> None:
    monkeypatch.setenv("WORKER_API_PROJECT_DIR", "/workspace/apps/api")
    monkeypatch.setenv("API_DATABASE_URL", "sqlite+pysqlite:////tmp/api.db")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434/v1")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:7b")
    monkeypatch.setenv("OLLAMA_EMBED_BASE_URL", "http://ollama:11434/v1")
    monkeypatch.setenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    monkeypatch.setenv("RAG_DB_PATH", "/workspace/data/rag_index/rag.db")
    monkeypatch.setenv("RAG_EXPECTED_EMBED_DIM", "768")

    captured: dict[str, object] = {}

    class _Completed:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = '{"ok": true}\n'
            self.stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return _Completed()

    monkeypatch.setattr("worker.main.subprocess.run", fake_run)

    result = _run_job_subprocess("rag_reindex_incremental", {"requested_by": "test"})

    assert result == {"ok": True}
    command = captured["command"]
    kwargs = captured["kwargs"]
    assert isinstance(command, list)
    assert isinstance(kwargs, dict)
    assert "api.services.rag.incremental_reindex_job_runner" in command
    assert "--payload-json" in command
    assert kwargs["cwd"] == "/workspace"
    env = kwargs["env"]
    assert isinstance(env, dict)
    assert env["API_DATABASE_URL"] == "sqlite+pysqlite:////tmp/api.db"
    assert env["OLLAMA_BASE_URL"] == "http://ollama:11434/v1"
    assert env["OLLAMA_MODEL"] == "qwen2.5:7b"
    assert env["OLLAMA_EMBED_MODEL"] == "nomic-embed-text"
    assert env["RAG_DB_PATH"] == "/workspace/data/rag_index/rag.db"
    assert env["RAG_EXPECTED_EMBED_DIM"] == "768"
