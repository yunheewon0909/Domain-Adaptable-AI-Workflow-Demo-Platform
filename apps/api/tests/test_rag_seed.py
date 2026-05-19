from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.db import get_engine
from api.models import RAGCollectionRecord, RAGDocumentRecord
from api.services.rag.collections import (
    _DEMO_SEED_COLLECTIONS,
    SEED_COLLECTION_OWNER_TAG,
    ensure_default_rag_collections,
)


_PLATFORM_TOOLS_PATH = (
    Path(__file__).resolve().parents[3]
    / "apps"
    / "api"
    / "src"
    / "api"
    / "static"
    / "openwebui"
    / "platform_tools.py"
)


def _load_platform_tools_module():
    spec = importlib.util.spec_from_file_location(
        "platform_tools_under_seed_test", _PLATFORM_TOOLS_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seed_runs_on_app_startup_and_populates_collections(client: TestClient) -> None:
    response = client.get("/rag-collections")
    assert response.status_code == 200
    collections = response.json()

    by_id = {item["id"]: item for item in collections}
    for spec in _DEMO_SEED_COLLECTIONS:
        assert spec.collection_id in by_id, (
            f"seeded collection {spec.collection_id} should be visible via /rag-collections"
        )
        seeded = by_id[spec.collection_id]
        assert seeded["name"] == spec.name
        assert seeded["document_count"] == len(spec.documents)
        assert seeded["chunking_policy_json"]["owner_tag"] == SEED_COLLECTION_OWNER_TAG
        filenames = {document["filename"] for document in seeded["documents"]}
        for doc_spec in spec.documents:
            assert doc_spec.filename in filenames
        for document in seeded["documents"]:
            assert document["source_type"] == "seed"
            assert document["preview_length"] > 0
            assert document["text_preview"], (
                "seed documents must carry text_preview so retrieval has something to match"
            )


def test_seed_retrieval_preview_returns_matches_for_demo_query(client: TestClient) -> None:
    target = _DEMO_SEED_COLLECTIONS[0]
    response = client.post(
        "/rag-retrieval/preview",
        json={
            "collection_id": target.collection_id,
            "query": "maintenance ingestion",
            "top_k": 3,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["collection_id"] == target.collection_id
    assert body["document_count"] == len(target.documents)
    assert body["results"], (
        "seeded ops handbook should return at least one match for a maintenance query"
    )
    excerpts = " \n".join(item["excerpt"] for item in body["results"])
    assert "maintenance" in excerpts.lower() or "ingestion" in excerpts.lower()


def test_seed_is_idempotent_when_invoked_repeatedly(client: TestClient) -> None:
    with Session(get_engine()) as session:
        first = ensure_default_rag_collections(session)
        second = ensure_default_rag_collections(session)
        assert first == second
        for spec in _DEMO_SEED_COLLECTIONS:
            collection = session.get(RAGCollectionRecord, spec.collection_id)
            assert collection is not None
            for doc_spec in spec.documents:
                document = session.get(RAGDocumentRecord, doc_spec.document_id)
                assert document is not None
                assert document.metadata_json["owner_tag"] == SEED_COLLECTION_OWNER_TAG


def test_seed_documents_are_deletable_and_not_restored_until_collection_removed(
    client: TestClient,
) -> None:
    target_collection = _DEMO_SEED_COLLECTIONS[0]
    target_doc = target_collection.documents[0]

    response = client.delete(f"/rag-documents/{target_doc.document_id}")
    assert response.status_code == 200

    with Session(get_engine()) as session:
        ensure_default_rag_collections(session)
        # Collection still exists, so the previously deleted seed document
        # must NOT be silently re-added — reviewers' explicit deletion wins.
        assert session.get(RAGDocumentRecord, target_doc.document_id) is None


def test_seed_collection_visible_to_open_webui_tool(client: TestClient) -> None:
    """End-to-end: the Open WebUI Tool's list_rag_collections sees the seed."""
    module = _load_platform_tools_module()
    tools = module.Tools()

    def _request_via_test_client(method: str, path: str, *, json_body=None):
        if method == "GET":
            res = client.get(path)
        elif method == "POST":
            res = client.post(path, json=json_body)
        else:
            raise AssertionError(f"unexpected method: {method}")
        try:
            return res.status_code, res.json()
        except ValueError:
            return res.status_code, {"raw": res.text}

    tools._request = _request_via_test_client  # type: ignore[attr-defined]

    listed = json.loads(tools.list_rag_collections())
    assert listed["ok"] is True
    seed_ids = {entry["id"] for entry in listed["collections"]}
    assert {spec.collection_id for spec in _DEMO_SEED_COLLECTIONS} <= seed_ids

    target = _DEMO_SEED_COLLECTIONS[0]
    queried = json.loads(
        tools.query_rag_collection(target.collection_id, "maintenance ingestion", top_k=3)
    )
    assert queried["ok"] is True
    assert queried["retrieval"]["collection_id"] == target.collection_id
    assert queried["retrieval"]["results"], (
        "Open WebUI Tool query must return non-empty results against the seeded collection"
    )
