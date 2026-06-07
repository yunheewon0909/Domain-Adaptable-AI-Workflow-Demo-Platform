from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.db import get_engine
from api.services.rag.graph_index import index_collection

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

_EXPECTED_METHODS = [
    "list_collections",
    "create_collection",
    "upload_text_document",
    "search_collection",
    "get_entity",
    "get_subgraph",
    "generate_evaluation_set",
    "run_rag_evaluation",
    "get_evaluation_report",
    "get_job_status",
]


def _load_platform_tools_module():
    spec = importlib.util.spec_from_file_location(
        "platform_tools_under_test", _PLATFORM_TOOLS_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---- Contract tests on the static artifact --------------------------------


def test_platform_tools_file_exists_and_parses() -> None:
    assert _PLATFORM_TOOLS_PATH.is_file()
    source = _PLATFORM_TOOLS_PATH.read_text(encoding="utf-8")
    ast.parse(source)
    assert "title: Domain Adaptable AI Platform" in source


def test_platform_tools_exposes_expected_methods() -> None:
    module = _load_platform_tools_module()
    tools_cls = getattr(module, "Tools", None)
    assert tools_cls is not None
    valves = tools_cls.Valves()
    assert valves.api_base_url == "http://api:8000"
    assert 1 <= valves.default_top_k <= 20

    instance = tools_cls()
    for method_name in _EXPECTED_METHODS:
        method = getattr(instance, method_name, None)
        assert callable(method), f"missing required tool method: {method_name}"
        assert method.__doc__, f"{method_name} must keep its docstring"


def test_platform_tools_methods_return_json_envelopes_on_transport_failure() -> None:
    module = _load_platform_tools_module()
    tools = module.Tools()
    tools.valves.api_base_url = "http://127.0.0.1:1"
    tools.valves.request_timeout_seconds = 1

    decoded = json.loads(tools.list_collections())
    assert decoded["ok"] is False
    assert decoded["action"] == "list_collections"
    assert "hint" in decoded


# ---- API endpoints that serve the artifact --------------------------------


def test_openwebui_platform_tools_endpoint_serves_python(client: TestClient) -> None:
    response = client.get("/openwebui/platform_tools.py")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/x-python")
    body = response.text
    assert "class Tools" in body
    for method_name in _EXPECTED_METHODS:
        assert f"def {method_name}" in body


def test_openwebui_manifest_describes_platform_tools(client: TestClient) -> None:
    response = client.get("/openwebui/manifest.json")
    assert response.status_code == 200
    tool = response.json()["tools"][0]
    assert tool["id"] == "platform_tools"
    assert tool["url_path"] == "/openwebui/platform_tools.py"
    assert set(tool["methods"]) >= set(_EXPECTED_METHODS)


# ---- End-to-end against the in-process TestClient -------------------------


@pytest.fixture
def platform_tools_against_client(client: TestClient):
    module = _load_platform_tools_module()
    tools = module.Tools()

    def _request_via_test_client(method: str, path: str, *, json_body=None):
        if method == "GET":
            response = client.get(path)
        elif method == "POST":
            response = client.post(path, json=json_body)
        elif method == "DELETE":
            response = client.delete(path)
        elif method == "PATCH":
            response = client.patch(path, json=json_body)
        else:
            raise AssertionError(f"unexpected method: {method}")
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {"raw": response.text}

    tools._request = _request_via_test_client  # type: ignore[attr-defined]
    return tools


def _fake_extractor(chunk: str) -> dict:
    return {
        "entities": [{"name": "Pump P-101", "type": "equipment", "description": "feed pump"}],
        "relationships": [],
    }


def test_collection_lifecycle_via_tool(platform_tools_against_client) -> None:
    tools = platform_tools_against_client

    created = json.loads(tools.create_collection("KB", "desc"))
    assert created["ok"] is True
    collection_id = created["result"]["id"]

    uploaded = json.loads(
        tools.upload_text_document(collection_id, "n.md", "Pump P-101 feeds the reactor.")
    )
    assert uploaded["ok"] is True

    listed = json.loads(tools.list_collections())
    assert listed["ok"] is True
    assert any(c["id"] == collection_id for c in listed["collections"])


def test_search_and_subgraph_via_tool(platform_tools_against_client) -> None:
    tools = platform_tools_against_client
    collection_id = json.loads(tools.create_collection("KB"))["result"]["id"]
    tools.upload_text_document(collection_id, "n.md", "Pump P-101 feeds the reactor.")
    # Index directly (the worker would normally do this).
    with Session(get_engine()) as session:
        index_collection(session, collection_id=collection_id, extractor=_fake_extractor)

    searched = json.loads(tools.search_collection(collection_id, "pump", mode="naive"))
    assert searched["ok"] is True
    assert searched["result"]["mode"] == "naive"

    subgraph = json.loads(tools.get_subgraph(collection_id))
    assert subgraph["ok"] is True
    assert subgraph["result"]["nodes"]


def test_get_job_status_error_envelope_for_missing(platform_tools_against_client) -> None:
    decoded = json.loads(platform_tools_against_client.get_job_status("does-not-exist"))
    assert decoded["ok"] is False
    assert decoded["action"] == "get_job_status"
    assert decoded["http_status"] == 404


def test_generate_evaluation_set_via_tool_requires_index(
    platform_tools_against_client,
) -> None:
    tools = platform_tools_against_client
    collection_id = json.loads(tools.create_collection("KB"))["result"]["id"]
    tools.upload_text_document(collection_id, "n.md", "Pump P-101 feeds the reactor.")
    # Not indexed yet -> 422 error envelope.
    decoded = json.loads(tools.generate_evaluation_set(collection_id, "eval"))
    assert decoded["ok"] is False
    assert decoded["http_status"] == 422
