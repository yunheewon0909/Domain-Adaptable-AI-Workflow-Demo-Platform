from __future__ import annotations

import json
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Callable, NoReturn
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_SKIP = 2

TERMINAL_JOB_STATUSES = {"succeeded", "failed"}


class E2EError(RuntimeError):
    pass


class E2ESkip(RuntimeError):
    pass


@dataclass
class HTTPResponse:
    status: int
    headers: dict[str, str]
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> object:
        return json.loads(self.text)


def print_step(message: str) -> None:
    print(f"[step] {message}")


def print_ok(message: str) -> None:
    print(f"[ok] {message}")


def print_warn(message: str) -> None:
    print(f"[warn] {message}")


def print_fail(message: str) -> None:
    print(f"[fail] {message}")


def fail(message: str) -> NoReturn:
    raise E2EError(message)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def examples_dir() -> Path:
    return repo_root() / "examples"


def api_base_url() -> str:
    return os.environ.get("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    if not isinstance(raw, str):
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def timestamp_suffix() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + f"-{uuid4().hex[:8]}"


def assert_non_empty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(f"{name} must be a non-empty string")
    return value.strip()


def as_int(value: object, name: str) -> int:
    if isinstance(value, bool):
        fail(f"{name} must be an integer value")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError as exc:
            fail(f"{name} must be an integer value")
            raise exc
    fail(f"{name} must be an integer value")


def ensure(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def json_dict(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        fail(f"{name} must be a JSON object")
    return value


def json_list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        fail(f"{name} must be a JSON list")
    return value


def _normalize_path(path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if path.startswith("/"):
        return api_base_url() + path
    return api_base_url() + "/" + path


def _encode_query(params: dict[str, object] | None) -> str:
    if not params:
        return ""
    items: list[tuple[str, str]] = []
    for key, value in params.items():
        if value is None:
            continue
        items.append((key, str(value)))
    if not items:
        return ""
    return "?" + urllib.parse.urlencode(items)


def request(
    method: str,
    path: str,
    *,
    json_body: object | None = None,
    headers: dict[str, str] | None = None,
    query: dict[str, object] | None = None,
    data: bytes | None = None,
    timeout_seconds: int = 30,
    expected_status: int | set[int] | None = None,
) -> HTTPResponse:
    request_headers = {"Accept": "application/json, text/plain, */*"}
    if headers:
        request_headers.update(headers)

    payload = data
    if json_body is not None:
        payload = json.dumps(json_body).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")

    url = _normalize_path(path) + _encode_query(query)
    req = urllib.request.Request(
        url,
        data=payload,
        headers=request_headers,
        method=method.upper(),
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            result = HTTPResponse(
                status=response.getcode(),
                headers=dict(response.headers.items()),
                body=response.read(),
            )
    except urllib.error.HTTPError as exc:
        result = HTTPResponse(
            status=exc.code,
            headers=dict(exc.headers.items()),
            body=exc.read(),
        )
    except urllib.error.URLError as exc:
        fail(f"HTTP request failed for {url}: {exc}")

    if expected_status is not None:
        allowed = (
            {expected_status}
            if isinstance(expected_status, int)
            else set(expected_status)
        )
        if result.status not in allowed:
            fail(
                f"Expected HTTP {sorted(allowed)} from {method.upper()} {url}, got {result.status}: {result.text}"
            )
    return result


def request_json(
    method: str,
    path: str,
    *,
    json_body: object | None = None,
    headers: dict[str, str] | None = None,
    query: dict[str, object] | None = None,
    timeout_seconds: int = 30,
    expected_status: int | set[int] | None = None,
) -> object:
    response = request(
        method,
        path,
        json_body=json_body,
        headers=headers,
        query=query,
        timeout_seconds=timeout_seconds,
        expected_status=expected_status,
    )
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        fail(
            f"Expected JSON from {method.upper()} {path}, got invalid payload: {response.text}"
        )
        raise exc


def request_multipart(
    method: str,
    path: str,
    *,
    fields: dict[str, str] | None = None,
    files: list[tuple[str, Path, str | None]] | None = None,
    query: dict[str, object] | None = None,
    timeout_seconds: int = 60,
    expected_status: int | set[int] | None = None,
) -> HTTPResponse:
    boundary = f"----e2e-{uuid4().hex}"
    chunks: list[bytes] = []

    for key, value in (fields or {}).items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )

    for field_name, file_path, explicit_type in files or []:
        content_type = explicit_type or mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{field_name}"; filename="{file_path.name}"\r\n'
                ).encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                file_path.read_bytes(),
                b"\r\n",
            ]
        )

    chunks.append(f"--{boundary}--\r\n".encode())
    return request(
        method,
        path,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        query=query,
        data=b"".join(chunks),
        timeout_seconds=timeout_seconds,
        expected_status=expected_status,
    )


def wait_for_api_health(timeout_seconds: int = 60) -> dict[str, object]:
    print_step(f"Waiting for API health at {api_base_url()}/health")
    deadline = time.time() + timeout_seconds
    last_error = "API health check did not succeed yet"
    while time.time() < deadline:
        try:
            payload = request_json("GET", "/health", timeout_seconds=5, expected_status=200)
            if isinstance(payload, dict):
                print_ok("API health check returned 200")
                return payload
            last_error = f"Unexpected /health payload: {payload!r}"
        except E2EError as exc:
            last_error = str(exc)
        time.sleep(2)
    fail(last_error)
    raise AssertionError("unreachable")


def _wait_for_terminal_payload(
    *,
    path: str,
    timeout_seconds: int,
    label: str,
    terminal_statuses: set[str] | None = None,
) -> dict[str, object]:
    statuses = terminal_statuses or TERMINAL_JOB_STATUSES
    deadline = time.time() + timeout_seconds
    last_status = "unknown"
    while time.time() < deadline:
        payload = json_dict(request_json("GET", path, expected_status=200), f"{label} payload")
        status = str(payload.get("status") or "").strip()
        last_status = status or "missing"
        if status in statuses:
            print_ok(f"{label} reached terminal status: {status}")
            return payload
        time.sleep(2)
    fail(f"Timed out waiting for {label}; last status was {last_status}")
    raise AssertionError("unreachable")


def wait_for_job(job_id: str, timeout_seconds: int = 120) -> dict[str, object]:
    return _wait_for_terminal_payload(
        path=f"/jobs/{job_id}", timeout_seconds=timeout_seconds, label=f"job {job_id}"
    )


def wait_for_ft_training_job(training_job_id: str, timeout_seconds: int = 180) -> dict[str, object]:
    return _wait_for_terminal_payload(
        path=f"/ft-training-jobs/{training_job_id}",
        timeout_seconds=timeout_seconds,
        label=f"FT training job {training_job_id}",
    )


def wait_for_plc_run(run_id: str, timeout_seconds: int = 120) -> dict[str, object]:
    return _wait_for_terminal_payload(
        path=f"/plc-test-runs/{run_id}", timeout_seconds=timeout_seconds, label=f"PLC run {run_id}"
    )


def list_models() -> list[dict[str, object]]:
    payload = json_list(request_json("GET", "/models", expected_status=200), "/models response")
    return [item for item in payload if isinstance(item, dict)]


def get_selectable_model(*, allow_skip: bool | None = None) -> dict[str, object]:
    allow_skip = env_flag("E2E_ALLOW_NO_MODEL_SKIP", False) if allow_skip is None else allow_skip
    for model in list_models():
        readiness = model.get("readiness")
        if isinstance(readiness, dict) and readiness.get("selectable") is True:
            print_ok(f"Selected runtime-ready model: {model.get('id')} ({model.get('display_name')})")
            return model
    message = "No runtime-ready/selectable model is available from /models"
    if allow_skip:
        raise E2ESkip(message)
    fail(message)
    raise AssertionError("unreachable")


def find_artifact_only_model() -> dict[str, object] | None:
    for model in list_models():
        readiness = model.get("readiness")
        if not isinstance(readiness, dict):
            continue
        if (
            model.get("source_type") == "fine_tuned"
            and model.get("status") == "artifact_ready"
            and readiness.get("selectable") is False
        ):
            return model
    return None


def choose_workflow_key(preferred: str = "briefing") -> str:
    payload = json_list(request_json("GET", "/workflows", expected_status=200), "/workflows response")
    keys = [str(item.get("key")) for item in payload if isinstance(item, dict)]
    if preferred in keys:
        return preferred
    if not keys:
        fail("No workflows are available from /workflows")
        raise AssertionError("unreachable")
    return keys[0]


def create_rag_collection(name: str, description: str | None = None) -> dict[str, object]:
    payload = json_dict(
        request_json(
        "POST",
        "/rag-collections",
        json_body={"name": name, "description": description},
        expected_status=201,
        ),
        "RAG collection payload",
    )
    return payload


def upload_rag_document(collection_id: str, file_path: Path, mime_type: str | None = None) -> dict[str, object]:
    response = request_multipart(
        "POST",
        f"/rag-collections/{collection_id}/documents",
        files=[("file", file_path, mime_type)],
        expected_status=201,
    )
    payload = json_dict(response.json(), "RAG document payload")
    return payload


def create_locked_ft_dataset(*, dataset_name: str, rows: list[dict[str, object]], version_label: str = "e2e-v1") -> dict[str, str]:
    dataset = json_dict(
        request_json(
        "POST",
        "/ft-datasets",
        json_body={
            "name": dataset_name,
            "task_type": "instruction_sft",
            "schema_type": "json",
            "description": "E2E smoke dataset",
        },
        expected_status=201,
        ),
        "FT dataset payload",
    )
    dataset_id = assert_non_empty_string(dataset.get("id"), "dataset_id")

    version = json_dict(
        request_json(
        "POST",
        f"/ft-datasets/{dataset_id}/versions",
        json_body={"version_label": version_label},
        expected_status=201,
        ),
        "FT dataset version payload",
    )
    version_id = assert_non_empty_string(version.get("id"), "version_id")

    request_json(
        "POST",
        f"/ft-dataset-versions/{version_id}/rows",
        json_body={"rows": rows},
        expected_status=201,
    )
    request_json(
        "POST",
        f"/ft-dataset-versions/{version_id}/status",
        json_body={"status": "validated"},
        expected_status=200,
    )
    request_json(
        "POST",
        f"/ft-dataset-versions/{version_id}/status",
        json_body={"status": "locked"},
        expected_status=200,
    )
    return {"dataset_id": dataset_id, "version_id": version_id}


def enqueue_ft_smoke_training(version_id: str, *, trainer_model_name: str = "hf-internal/testing-tiny-random-gpt2") -> dict[str, object]:
    payload = json_dict(
        request_json(
        "POST",
        "/ft-training-jobs",
        json_body={
            "dataset_version_id": version_id,
            "base_model_name": "qwen2.5:7b-instruct-q4_K_M",
            "training_method": "sft_lora",
            "hyperparams_json": {
                "smoke_test": True,
                "epochs": 1,
                "batch_size": 1,
                "gradient_accumulation_steps": 1,
                "max_seq_length": 256,
                "lora_r": 4,
                "lora_alpha": 8,
                "lora_dropout": 0.0,
                "seed": 42,
                "trainer_model_name": trainer_model_name,
            },
        },
        expected_status=202,
        ),
        "FT training job payload",
    )
    return payload


def default_ft_rows() -> list[dict[str, object]]:
    return [
        {
            "split": "train",
            "input_json": {
                "instruction": "summarize",
                "input": "workflow reviewer should stay grounded in evidence",
            },
            "target_json": {"output": "grounded workflow summary"},
            "metadata_json": {"source": "e2e", "smoke_test": True},
        },
        {
            "split": "val",
            "input_json": {
                "instruction": "classify",
                "input": "artifact-ready models are review-only",
            },
            "target_json": {"output": "review_only"},
            "metadata_json": {"source": "e2e", "smoke_test": True},
        },
    ]


def artifact_path(path_value: object) -> Path:
    return Path(assert_non_empty_string(path_value, "artifact path"))


def run_main(main_func: Callable[[], None]) -> None:
    try:
        main_func()
    except E2ESkip as exc:
        print_warn(str(exc))
        raise SystemExit(EXIT_SKIP) from exc
    except E2EError as exc:
        print_fail(str(exc))
        raise SystemExit(EXIT_FAIL) from exc
    raise SystemExit(EXIT_OK)
