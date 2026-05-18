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

    instance = tools_cls()
    for method_name in (
        "list_rag_collections",
        "query_rag_collection",
        "list_workflows",
        "enqueue_workflow_job",
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
    assert "def list_workflows" in body
    assert "def enqueue_workflow_job" in body
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
        "list_workflows",
        "enqueue_workflow_job",
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
