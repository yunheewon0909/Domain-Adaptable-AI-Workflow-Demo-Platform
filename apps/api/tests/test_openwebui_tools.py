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
    assert valves.api_base_url == "http://host.docker.internal:8000"
    assert valves.request_timeout_seconds >= 1
    assert 1 <= valves.default_top_k <= 10

    instance = tools_cls()
    for method_name in (
        "list_rag_collections",
        "query_rag_collection",
        "get_rag_collection",
        "list_rag_documents",
        "get_rag_document",
        "delete_rag_document",
        "delete_rag_collection",
        "list_selectable_models",
        "list_platform_models",
        "get_model_detail",
        "run_platform_inference",
        "get_job_status",
        "summarize_job_result",
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
    assert "def delete_rag_collection" in body
    assert "def list_selectable_models" in body
    assert "def list_platform_models" in body
    assert "def get_model_detail" in body
    assert "def run_platform_inference" in body
    assert "def get_job_status" in body
    assert "def summarize_job_result" in body


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
        "delete_rag_collection",
        "list_selectable_models",
        "list_platform_models",
        "get_model_detail",
        "run_platform_inference",
        "get_job_status",
        "summarize_job_result",
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


def test_delete_rag_collection_returns_success_envelope() -> None:
    module = _load_platform_tools_module()
    tools = module.Tools()

    canned = {
        "collection_id": "rag-c1",
        "deleted": True,
        "document_count": 3,
        "storage_deleted": True,
    }
    tools._request = lambda method, path, *, json_body=None: (200, canned)  # type: ignore[attr-defined]

    decoded = json.loads(tools.delete_rag_collection("rag-c1"))
    assert decoded["ok"] is True
    assert decoded["action"] == "delete_rag_collection"
    assert decoded["collection_id"] == "rag-c1"
    assert decoded["deleted"] is True
    assert decoded["document_count"] == 3
    assert decoded["storage_deleted"] is True


def test_delete_rag_collection_returns_error_for_missing() -> None:
    module = _load_platform_tools_module()
    tools = module.Tools()

    canned_error = {"detail": "RAG collection not found"}
    tools._request = lambda method, path, *, json_body=None: (  # type: ignore[attr-defined]
        404,
        canned_error,
    )

    decoded = json.loads(tools.delete_rag_collection("does-not-exist"))
    assert decoded["ok"] is False
    assert decoded["action"] == "delete_rag_collection"
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


def test_list_selectable_models_returns_only_selectable() -> None:
    module = _load_platform_tools_module()
    tools = module.Tools()

    canned_models = [
        {
            "id": "model-1",
            "display_name": "GPT-4",
            "status": "active",
            "publish_status": "published",
            "source_type": "base",
            "description": "ready model",
            "tags_json": ["chat"],
            "readiness": {"selectable": True, "selectable_reason": None},
        },
        {
            "id": "model-2",
            "display_name": "Review-Only",
            "status": "registered",
            "publish_status": "draft",
            "source_type": "trained",
            "description": "not ready",
            "tags_json": [],
            "readiness": {
                "selectable": False,
                "selectable_reason": "awaiting review",
            },
        },
    ]
    tools._request = lambda method, path, *, json_body=None: (200, canned_models)  # type: ignore[attr-defined]

    decoded = json.loads(tools.list_selectable_models())
    assert decoded["ok"] is True
    assert len(decoded["models"]) == 1
    assert decoded["models"][0]["model_id"] == "model-1"
    assert decoded["models"][0]["selectable"] is True
    assert decoded["models"][0]["name"] == "GPT-4"
    assert decoded["models"][0]["tags"] == ["chat"]


def _canned_models_fixture() -> list[dict]:
    return [
        {
            "id": "model-1",
            "display_name": "GPT-4",
            "status": "active",
            "publish_status": "published",
            "source_type": "base",
            "description": "ready model",
            "tags_json": ["chat"],
            "readiness": {"selectable": True, "selectable_reason": None},
            "warnings": [],
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-02T00:00:00Z",
        },
        {
            "id": "model-2",
            "display_name": "Review-Only",
            "status": "registered",
            "publish_status": "draft",
            "source_type": "trained",
            "description": "not ready",
            "tags_json": [],
            "readiness": {
                "selectable": False,
                "selectable_reason": "awaiting review",
            },
            "warnings": ["missing artifact"],
            "created_at": "2025-01-03T00:00:00Z",
            "updated_at": "2025-01-04T00:00:00Z",
        },
    ]


def test_list_platform_models_default_returns_selectable_only() -> None:
    module = _load_platform_tools_module()
    tools = module.Tools()
    tools._request = lambda method, path, *, json_body=None: (200, _canned_models_fixture())  # type: ignore[attr-defined]

    decoded = json.loads(tools.list_platform_models())
    assert decoded["ok"] is True
    assert decoded["total"] == 2
    assert decoded["selectable_count"] == 1
    assert len(decoded["models"]) == 1
    assert decoded["models"][0]["model_id"] == "model-1"
    assert decoded["models"][0]["selectable"] is True


def test_list_platform_models_include_review_only_returns_all() -> None:
    module = _load_platform_tools_module()
    tools = module.Tools()
    tools._request = lambda method, path, *, json_body=None: (200, _canned_models_fixture())  # type: ignore[attr-defined]

    decoded = json.loads(tools.list_platform_models(include_review_only=True))
    assert decoded["ok"] is True
    assert decoded["total"] == 2
    assert decoded["selectable_count"] == 1
    assert len(decoded["models"]) == 2
    ids = {m["model_id"] for m in decoded["models"]}
    assert ids == {"model-1", "model-2"}
    by_id = {m["model_id"]: m for m in decoded["models"]}
    assert by_id["model-2"]["selectable"] is False
    assert by_id["model-2"]["selectable_reason"] == "awaiting review"


def test_list_platform_models_returns_error_envelope() -> None:
    module = _load_platform_tools_module()
    tools = module.Tools()
    tools._request = lambda method, path, *, json_body=None: (500, {"detail": "boom"})  # type: ignore[attr-defined]

    decoded = json.loads(tools.list_platform_models())
    assert decoded["ok"] is False
    assert decoded["action"] == "list_platform_models"
    assert decoded["http_status"] == 500


def test_get_model_detail_returns_projected_with_warnings_and_timestamps() -> None:
    module = _load_platform_tools_module()
    tools = module.Tools()

    canned = _canned_models_fixture()[1]
    calls: list[tuple[str, str]] = []

    def _fake_request(method, path, *, json_body=None):
        calls.append((method, path))
        return 200, canned

    tools._request = _fake_request  # type: ignore[attr-defined]

    decoded = json.loads(tools.get_model_detail("model-2"))
    assert decoded["ok"] is True
    assert calls == [("GET", "/models/model-2")]
    model = decoded["model"]
    assert model["model_id"] == "model-2"
    assert model["name"] == "Review-Only"
    assert model["selectable"] is False
    assert model["selectable_reason"] == "awaiting review"
    assert model["warnings"] == ["missing artifact"]
    assert model["created_at"] == "2025-01-03T00:00:00Z"
    assert model["updated_at"] == "2025-01-04T00:00:00Z"


def test_get_model_detail_returns_error_envelope_for_missing() -> None:
    module = _load_platform_tools_module()
    tools = module.Tools()
    tools._request = lambda method, path, *, json_body=None: (404, {"detail": "Model not found"})  # type: ignore[attr-defined]

    decoded = json.loads(tools.get_model_detail("does-not-exist"))
    assert decoded["ok"] is False
    assert decoded["action"] == "get_model_detail"
    assert decoded["http_status"] == 404


def test_run_platform_inference_returns_answer() -> None:
    module = _load_platform_tools_module()
    tools = module.Tools()

    calls: list[tuple[str, str, dict | None]] = []

    def _fake_request(method, path, *, json_body=None):
        calls.append((method, path, json_body))
        return 200, {
            "answer": "42",
            "model_id": "model-1",
            "usage": {"prompt_tokens": 5, "completion_tokens": 1},
        }

    tools._request = _fake_request  # type: ignore[attr-defined]

    decoded = json.loads(
        tools.run_platform_inference("model-1", "what is the answer?")
    )
    assert decoded["ok"] is True
    assert decoded["answer"] == "42"
    assert decoded["model_id"] == "model-1"
    assert decoded["usage"] == {"prompt_tokens": 5, "completion_tokens": 1}
    assert calls == [
        ("POST", "/inference/run", {"model_id": "model-1", "prompt": "what is the answer?"})
    ]


def test_run_platform_inference_passes_rag_collection_and_top_k() -> None:
    module = _load_platform_tools_module()
    tools = module.Tools()

    calls: list[tuple[str, str, dict | None]] = []

    def _fake_request(method, path, *, json_body=None):
        calls.append((method, path, json_body))
        return 200, {"answer": "grounded", "model_id": "model-1"}

    tools._request = _fake_request  # type: ignore[attr-defined]

    decoded = json.loads(
        tools.run_platform_inference(
            "model-1",
            "summarize maintenance",
            rag_collection_id="rag-c1",
            top_k=20,
        )
    )
    assert decoded["ok"] is True
    assert calls[0] == (
        "POST",
        "/inference/run",
        {
            "model_id": "model-1",
            "prompt": "summarize maintenance",
            "rag_collection_id": "rag-c1",
            "top_k": 10,
        },
    )


def test_run_platform_inference_returns_error_envelope_on_failure() -> None:
    module = _load_platform_tools_module()
    tools = module.Tools()
    tools._request = lambda method, path, *, json_body=None: (  # type: ignore[attr-defined]
        500,
        {"detail": "Ollama unreachable"},
    )

    decoded = json.loads(tools.run_platform_inference("model-1", "hi"))
    assert decoded["ok"] is False
    assert decoded["action"] == "run_platform_inference"
    assert decoded["http_status"] == 500


def test_summarize_job_result_returns_summary_for_succeeded() -> None:
    module = _load_platform_tools_module()
    tools = module.Tools()

    canned_job = {
        "id": "job-1",
        "status": "succeeded",
        "workflow_key": "briefing",
        "result_json": {
            "summary": "All systems nominal",
            "confidence": 0.95,
            "timing": {"elapsed_ms": 1200},
        },
    }
    tools._request = lambda method, path, *, json_body=None: (200, canned_job)  # type: ignore[attr-defined]

    decoded = json.loads(tools.summarize_job_result("job-1"))
    assert decoded["ok"] is True
    assert decoded["status"] == "succeeded"
    assert decoded["summary"]["summary"] == "All systems nominal"
    assert decoded["summary"]["confidence"] == 0.95
    assert "timing" not in decoded["summary"]


def test_summarize_job_result_returns_error_for_failed() -> None:
    module = _load_platform_tools_module()
    tools = module.Tools()

    canned_job = {
        "id": "job-2",
        "status": "failed",
        "workflow_key": "briefing",
        "error": "Dataset not found: ops",
    }
    tools._request = lambda method, path, *, json_body=None: (200, canned_job)  # type: ignore[attr-defined]

    decoded = json.loads(tools.summarize_job_result("job-2"))
    assert decoded["ok"] is False
    assert decoded["status"] == "failed"
    assert decoded["error"] == "Dataset not found: ops"
    assert "suggestion" in decoded


def test_summarize_job_result_returns_status_for_running() -> None:
    module = _load_platform_tools_module()
    tools = module.Tools()

    canned_job = {
        "id": "job-3",
        "status": "running",
        "workflow_key": "briefing",
    }
    tools._request = lambda method, path, *, json_body=None: (200, canned_job)  # type: ignore[attr-defined]

    decoded = json.loads(tools.summarize_job_result("job-3"))
    assert decoded["ok"] is True
    assert decoded["status"] == "running"
    assert decoded["summary"] is None
    assert "next_step" in decoded

