from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


_REPO_ROOT = Path(__file__).resolve().parents[3]
_PLATFORM_TOOLS_PATH = (
    _REPO_ROOT
    / "apps"
    / "api"
    / "src"
    / "api"
    / "static"
    / "openwebui"
    / "platform_tools.py"
)


# ---- Contract tests on the static Open WebUI Tool artifact -----------------


def test_platform_tools_file_exists_and_parses() -> None:
    assert _PLATFORM_TOOLS_PATH.is_file(), (
        "platform_tools.py is missing; Open WebUI Tool artifact must ship with the API"
    )
    source = _PLATFORM_TOOLS_PATH.read_text(encoding="utf-8")
    ast.parse(source)
    assert "title: Domain Adaptable AI Platform" in source, (
        "Open WebUI parses metadata from the module docstring; the title header must remain"
    )


def _load_platform_tools_module():
    spec = importlib.util.spec_from_file_location(
        "platform_tools_under_test", _PLATFORM_TOOLS_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_platform_tools_exposes_expected_methods() -> None:
    module = _load_platform_tools_module()

    tools_cls = getattr(module, "Tools", None)
    assert tools_cls is not None, "Open WebUI expects a top-level `Tools` class"

    valves_cls = getattr(tools_cls, "Valves", None)
    assert valves_cls is not None, "Open WebUI expects a nested `Valves` Pydantic model"
    valves = valves_cls()
    assert valves.api_base_url == "http://api:8000"
    assert valves.request_timeout_seconds >= 1
    assert 1 <= valves.default_top_k <= 10
    assert 1 <= valves.workflow_wait_timeout_seconds <= 600
    assert 1 <= valves.workflow_poll_interval_seconds <= 30

    instance = tools_cls()
    for method_name in (
        "list_rag_collections",
        "query_rag_collection",
        "get_rag_collection",
        "list_rag_documents",
        "get_rag_document",
        "delete_rag_document",
        "list_workflows",
        "enqueue_workflow_job",
        "run_workflow_and_wait",
        "get_job_status",
    ):
        method = getattr(instance, method_name, None)
        assert callable(method), f"missing required tool method: {method_name}"
        assert method.__doc__, (
            f"{method_name} must keep its docstring so Open WebUI shows a "
            "description in the chat's tool picker"
        )


def test_platform_tools_methods_return_json_envelopes_on_transport_failure() -> None:
    module = _load_platform_tools_module()
    tools = module.Tools()
    # Point at a port nothing is listening on so the urllib request fails fast
    # and we exercise the error envelope path without hitting the network.
    tools.valves.api_base_url = "http://127.0.0.1:1"
    tools.valves.request_timeout_seconds = 1

    raw = tools.list_rag_collections()
    decoded = json.loads(raw)
    assert decoded["ok"] is False
    assert decoded["action"] == "list_rag_collections"
    assert "hint" in decoded


# ---- API endpoint that serves the artifact ---------------------------------


def test_openwebui_platform_tools_endpoint_serves_python(client: TestClient) -> None:
    response = client.get("/openwebui/platform_tools.py")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/x-python")
    body = response.text
    assert "class Tools" in body
    assert "class Valves" in body
    assert "def list_rag_collections" in body
    assert "def query_rag_collection" in body
    assert "def get_rag_collection" in body
    assert "def list_rag_documents" in body
    assert "def get_rag_document" in body
    assert "def delete_rag_document" in body
    assert "def list_workflows" in body
    assert "def enqueue_workflow_job" in body
    assert "def run_workflow_and_wait" in body
    assert "def get_job_status" in body


def test_openwebui_manifest_describes_platform_tools(client: TestClient) -> None:
    response = client.get("/openwebui/manifest.json")

    assert response.status_code == 200
    body = response.json()
    assert "tools" in body and body["tools"], "manifest must advertise at least one tool"
    tool = body["tools"][0]
    assert tool["id"] == "platform_tools"
    assert tool["url_path"] == "/openwebui/platform_tools.py"
    assert set(tool["methods"]) >= {
        "list_rag_collections",
        "query_rag_collection",
        "get_rag_collection",
        "list_rag_documents",
        "get_rag_document",
        "delete_rag_document",
        "list_workflows",
        "enqueue_workflow_job",
        "run_workflow_and_wait",
        "get_job_status",
    }


# ---- End-to-end: artifact methods talk to the real running API -------------


@pytest.fixture
def platform_tools_against_client(client: TestClient):
    """Wire the static Tool module into the in-process TestClient.

    The artifact normally speaks to the real API over HTTP; in tests we
    monkey-patch its ``_request`` method to use the FastAPI TestClient. This
    proves the tool's URL paths and JSON shapes still match the live API.
    """
    module = _load_platform_tools_module()
    tools = module.Tools()

    def _request_via_test_client(
        method: str,
        path: str,
        *,
        json_body=None,
    ):
        if method == "GET":
            response = client.get(path)
        elif method == "POST":
            response = client.post(path, json=json_body)
        elif method == "DELETE":
            response = client.delete(path)
        else:
            raise AssertionError(f"unexpected method: {method}")
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {"raw": response.text}

    tools._request = _request_via_test_client  # type: ignore[attr-defined]
    return tools


def test_list_rag_collections_uses_real_endpoint(platform_tools_against_client) -> None:
    raw = platform_tools_against_client.list_rag_collections()
    decoded = json.loads(raw)
    assert decoded["ok"] is True
    assert isinstance(decoded["collections"], list)


def test_list_workflows_uses_real_endpoint(platform_tools_against_client) -> None:
    raw = platform_tools_against_client.list_workflows()
    decoded = json.loads(raw)
    assert decoded["ok"] is True
    assert isinstance(decoded["workflows"], list)
    assert decoded["workflows"], "default starter ships at least one workflow"
    first = decoded["workflows"][0]
    assert "key" in first and "title" in first


def test_get_job_status_returns_error_envelope_for_missing_job(
    platform_tools_against_client,
) -> None:
    raw = platform_tools_against_client.get_job_status("does-not-exist")
    decoded = json.loads(raw)
    assert decoded["ok"] is False
    assert decoded["action"] == "get_job_status"
    assert decoded["http_status"] == 404


def test_list_rag_collections_returns_compact_projection() -> None:
    module = _load_platform_tools_module()
    tools = module.Tools()

    canned = [
        {
            "id": "rag-c1",
            "name": "Ops",
            "description": "ops handbook",
            "embedding_model": "nomic-embed-text",
            "document_count": 1,
            "chunking_policy_json": {"chunk_size": 800, "chunk_overlap": 100},
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-02T00:00:00Z",
            "documents": [
                {
                    "id": "rag-doc-1",
                    "filename": "maintenance.md",
                    "text_preview": "x" * 4000,
                    "metadata_json": {"text_preview": "x" * 4000},
                }
            ],
        }
    ]
    tools._request = lambda method, path, *, json_body=None: (200, canned)  # type: ignore[attr-defined]

    decoded = json.loads(tools.list_rag_collections())
    assert decoded["ok"] is True
    entry = decoded["collections"][0]
    assert entry["id"] == "rag-c1"
    assert entry["name"] == "Ops"
    assert entry["document_count"] == 1
    assert entry["document_filenames"] == ["maintenance.md"]
    for noisy_key in ("documents", "chunking_policy_json", "created_at", "updated_at"):
        assert noisy_key not in entry, (
            f"{noisy_key} should be projected out to keep the chat tool context lean"
        )


def test_query_rag_collection_returns_compact_projection() -> None:
    module = _load_platform_tools_module()
    tools = module.Tools()

    canned_retrieval = {
        "collection_id": "rag-c1",
        "collection_name": "Ops",
        "document_count": 2,
        "query": "maintenance ingestion",
        "top_k": 3,
        "results": [
            {
                "filename": "maintenance.md",
                "score": 2,
                "excerpt": "a" * 900,
                "metadata_json": {"raw": "x" * 2000},
            }
        ],
    }
    tools._request = lambda method, path, *, json_body=None: (200, canned_retrieval)  # type: ignore[attr-defined]

    decoded = json.loads(
        tools.query_rag_collection("rag-c1", "maintenance ingestion", top_k=3)
    )
    assert decoded["ok"] is True
    retrieval = decoded["retrieval"]
    assert retrieval["collection_id"] == "rag-c1"
    assert retrieval["results"][0]["filename"] == "maintenance.md"
    assert len(retrieval["results"][0]["excerpt"]) == 500
    assert "metadata_json" not in retrieval["results"][0]
    assert "document_count" not in retrieval


def test_list_workflows_returns_compact_projection() -> None:
    module = _load_platform_tools_module()
    tools = module.Tools()

    canned_workflows = [
        {
            "key": "briefing",
            "title": "Briefing",
            "description": "Summarize evidence",
            "prompt_label": "Briefing prompt",
            "output_fields": ["summary"],
            "created_at": "2025-01-01T00:00:00Z",
            "implementation_detail": "x" * 2000,
        }
    ]
    tools._request = lambda method, path, *, json_body=None: (200, canned_workflows)  # type: ignore[attr-defined]

    decoded = json.loads(tools.list_workflows())
    assert decoded["ok"] is True
    workflow = decoded["workflows"][0]
    assert workflow["key"] == "briefing"
    assert workflow["summary"] == "Summarize evidence"
    assert workflow["output_fields"] == ["summary"]
    assert "created_at" not in workflow
    assert "implementation_detail" not in workflow


def test_enqueue_workflow_job_promotes_job_id_for_chat_followup() -> None:
    module = _load_platform_tools_module()
    tools = module.Tools()

    canned_job = {
        "job_id": "job-42",
        "status": "queued",
        "workflow_key": "briefing",
        "dataset_key": None,
    }
    tools._request = lambda method, path, *, json_body=None: (202, canned_job)  # type: ignore[attr-defined]

    decoded = json.loads(
        tools.enqueue_workflow_job(
            "briefing",
            "maintenance ingestion briefing",
            rag_collection_id="rag-c1",
            top_k=2,
        )
    )
    assert decoded["ok"] is True
    assert decoded["job_id"] == "job-42"
    assert decoded["status"] == "queued"
    assert "job_id='job-42'" in decoded["next_step"]
    assert "payload_json" not in decoded["job"]


def test_run_workflow_and_wait_returns_completed_job_without_placeholder_polling() -> None:
    module = _load_platform_tools_module()
    tools = module.Tools()
    tools.valves.workflow_poll_interval_seconds = 1

    calls = []
    queued_job = {
        "job_id": "job-42",
        "status": "queued",
        "workflow_key": "briefing",
        "dataset_key": None,
    }
    completed_job = {
        "id": "job-42",
        "status": "succeeded",
        "workflow_key": "briefing",
        "dataset_key": None,
        "payload_json": {"prompt": "x" * 1000},
        "result_json": {"summary": "done"},
        "attempts": 1,
        "max_attempts": 1,
    }

    def _fake_request(method, path, *, json_body=None):
        calls.append((method, path, json_body))
        if method == "POST":
            return 202, queued_job
        return 200, completed_job

    tools._request = _fake_request  # type: ignore[attr-defined]

    decoded = json.loads(
        tools.run_workflow_and_wait(
            "briefing",
            "maintenance ingestion briefing",
            rag_collection_id="rag-c1",
            top_k=2,
            max_wait_seconds=2,
        )
    )
    assert decoded["ok"] is True
    assert decoded["job_id"] == "job-42"
    assert decoded["status"] == "succeeded"
    assert decoded["job"]["result_json"] == {"summary": "done"}
    assert "payload_json" not in decoded["job"]
    assert calls[0] == (
        "POST",
        "/workflows/briefing/jobs",
        {"prompt": "maintenance ingestion briefing", "rag_collection_id": "rag-c1", "k": 2},
    )
    assert calls[1][0:2] == ("GET", "/jobs/job-42")


def test_run_workflow_and_wait_times_out_with_real_job_id_for_later_polling() -> None:
    module = _load_platform_tools_module()
    tools = module.Tools()
    tools.valves.workflow_poll_interval_seconds = 1

    queued_job = {
        "job_id": "job-99",
        "status": "running",
        "workflow_key": "briefing",
    }
    tools._request = lambda method, path, *, json_body=None: (202 if method == "POST" else 200, queued_job)  # type: ignore[attr-defined]

    decoded = json.loads(
        tools.run_workflow_and_wait("briefing", "slow prompt", max_wait_seconds=1)
    )
    assert decoded["ok"] is True
    assert decoded["job_id"] == "job-99"
    assert decoded["status"] == "timeout"
    assert "job_id='job-99'" in decoded["next_step"]


def test_get_rag_collection_uses_real_endpoint(
    platform_tools_against_client,
) -> None:
    """Call get_rag_collection with a non-existent id via the TestClient.

    The endpoint returns 404, which exercises the error envelope path through
    the real API routing while proving the URL path and method match.
    """
    raw = platform_tools_against_client.get_rag_collection("does-not-exist")
    decoded = json.loads(raw)
    assert decoded["ok"] is False
    assert decoded["action"] == "get_rag_collection"
    assert decoded["http_status"] == 404


def test_list_rag_documents_returns_compact_projection() -> None:
    module = _load_platform_tools_module()
    tools = module.Tools()

    canned = [
        {
            "id": "rag-doc-1",
            "collection_id": "rag-c1",
            "filename": "maintenance.md",
            "mime_type": "text/markdown",
            "source_type": "upload",
            "status": "parsed",
            "checksum": "abc123",
            "metadata_json": {
                "text_preview": "x" * 4000,
                "text_length": 4000,
                "owner_tag": "ops",
                "parse_method": "utf8",
            },
            "text_preview": "x" * 4000,
            "preview_length": 4000,
            "preview_excerpt": "x" * 500,
            "parse_method": "utf8",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-02T00:00:00Z",
        }
    ]
    tools._request = lambda method, path, *, json_body=None: (200, canned)  # type: ignore[attr-defined]

    decoded = json.loads(
        tools.list_rag_documents("rag-c1")
    )
    assert decoded["ok"] is True
    assert decoded["collection_id"] == "rag-c1"
    entry = decoded["documents"][0]
    assert entry["id"] == "rag-doc-1"
    assert entry["filename"] == "maintenance.md"
    assert entry["mime_type"] == "text/markdown"
    assert entry["size_bytes"] == 4000
    assert entry["owner_tag"] == "ops"
    assert "text_preview" not in entry, (
        "text_preview should be omitted from listing projection"
    )


def test_get_rag_document_returns_detail_with_truncated_preview() -> None:
    module = _load_platform_tools_module()
    tools = module.Tools()

    canned = {
        "id": "rag-doc-2",
        "collection_id": "rag-c1",
        "filename": "runbook.md",
        "mime_type": "text/markdown",
        "source_type": "upload",
        "status": "parsed",
        "checksum": "def456",
        "metadata_json": {
            "text_preview": "A" * 3000,
            "text_length": 3000,
            "owner_tag": "ops",
            "parse_method": "utf8",
        },
        "text_preview": "A" * 3000,
        "preview_length": 3000,
        "preview_excerpt": "A" * 500,
        "parse_method": "utf8",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-02T00:00:00Z",
    }
    tools._request = lambda method, path, *, json_body=None: (200, canned)  # type: ignore[attr-defined]

    decoded = json.loads(tools.get_rag_document("rag-doc-2"))
    assert decoded["ok"] is True
    doc = decoded["document"]
    assert doc["id"] == "rag-doc-2"
    assert doc["filename"] == "runbook.md"
    # text_preview should be truncated to 1000 chars
    assert len(doc["text_preview"]) == 1000, (
        "text_preview must be truncated to 1000 characters"
    )
    assert doc["text_preview"] == "A" * 1000
    assert doc["size_bytes"] == 3000
    assert doc["owner_tag"] == "ops"


def test_delete_rag_document_returns_success_envelope() -> None:
    module = _load_platform_tools_module()
    tools = module.Tools()

    canned = {
        "document_id": "rag-doc-1",
        "collection_id": "rag-c1",
        "deleted": True,
        "storage_deleted": False,
    }
    tools._request = lambda method, path, *, json_body=None: (200, canned)  # type: ignore[attr-defined]

    decoded = json.loads(tools.delete_rag_document("rag-doc-1"))
    assert decoded["ok"] is True
    assert decoded["action"] == "delete_rag_document"
    assert decoded["document_id"] == "rag-doc-1"
    assert decoded["deleted"] is True


def test_delete_rag_document_returns_error_for_missing() -> None:
    module = _load_platform_tools_module()
    tools = module.Tools()

    canned_error = {"detail": "RAG document not found"}
    tools._request = lambda method, path, *, json_body=None: (  # type: ignore[attr-defined]
        404,
        canned_error,
    )

    decoded = json.loads(tools.delete_rag_document("does-not-exist"))
    assert decoded["ok"] is False
    assert decoded["action"] == "delete_rag_document"
    assert decoded["http_status"] == 404


def test_get_rag_collection_detail_via_e2e_returns_404_for_missing(
    platform_tools_against_client,
) -> None:
    """E2E: calling get_rag_collection on a non-existent id returns a 404 error envelope."""
    raw = platform_tools_against_client.get_rag_collection("does-not-exist-e2e")
    decoded = json.loads(raw)
    assert decoded["ok"] is False
    assert decoded["http_status"] == 404


def test_list_rag_documents_via_e2e(platform_tools_against_client) -> None:
    """E2E: listing documents for a non-existent collection returns a 404 error envelope."""
    raw = platform_tools_against_client.list_rag_documents("does-not-exist-collection")
    decoded = json.loads(raw)
    assert decoded["ok"] is False
    assert decoded["http_status"] == 404


def test_delete_rag_document_via_e2e(platform_tools_against_client) -> None:
    """E2E: deleting a non-existent document returns a 404 error envelope."""
    raw = platform_tools_against_client.delete_rag_document("does-not-exist-doc")
    decoded = json.loads(raw)
    assert decoded["ok"] is False
    assert decoded["http_status"] == 404


def test_get_job_status_returns_compact_projection() -> None:
    module = _load_platform_tools_module()
    tools = module.Tools()

    canned_job = {
        "id": "job-1",
        "type": "workflow_run",
        "status": "succeeded",
        "workflow_key": "briefing",
        "dataset_key": "ops",
        "plc_suite_id": None,
        "payload_json": {"prompt": "long", "evidence": ["x" * 2000]},
        "result_json": {"answer": "ok"},
        "attempts": 1,
        "max_attempts": 1,
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:01:00Z",
        "started_at": "2025-01-01T00:00:10Z",
        "finished_at": "2025-01-01T00:00:55Z",
        "error": None,
    }
    tools._request = lambda method, path, *, json_body=None: (200, canned_job)  # type: ignore[attr-defined]

    decoded = json.loads(tools.get_job_status("job-1"))
    assert decoded["ok"] is True
    job = decoded["job"]
    assert job["status"] == "succeeded"
    assert job["result_json"] == {"answer": "ok"}
    assert "payload_json" not in job, (
        "payload_json is the request input; dropping it keeps polling responses small"
    )
