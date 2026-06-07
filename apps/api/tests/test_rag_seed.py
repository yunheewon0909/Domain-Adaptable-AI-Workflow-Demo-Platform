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


def test_seed_resync_updates_stale_description_and_embedding_model(
    client: TestClient, monkeypatch,
) -> None:
    """ensure_default_rag_collections re-syncs description + embedding_model
    on seed-owned rows when the spec drifts (e.g. legacy `nomic-embed-text`
    rows from before the LM Studio cut-over). Reviewer-modified rows
    (owner_tag stripped) are left alone.
    """
    from api.config import get_settings

    monkeypatch.setenv("LMSTUDIO_EMBED_MODEL", "text-embedding-nomic-embed-text-v1.5")
    get_settings.cache_clear()

    target = _DEMO_SEED_COLLECTIONS[0]
    with Session(get_engine()) as session:
        collection = session.get(RAGCollectionRecord, target.collection_id)
        assert collection is not None
        collection.description = "STALE legacy description"
        collection.embedding_model = "nomic-embed-text"
        session.commit()

    with Session(get_engine()) as session:
        ensure_default_rag_collections(session)
        refreshed = session.get(RAGCollectionRecord, target.collection_id)
        assert refreshed is not None
        # description and embedding_model both re-synced from the spec
        assert refreshed.description == target.description
        assert refreshed.embedding_model == "text-embedding-nomic-embed-text-v1.5"


def test_seed_resync_leaves_reviewer_modified_rows_alone(
    client: TestClient, monkeypatch,
) -> None:
    """If the reviewer stripped the seed owner_tag, ensure_default_rag_
    collections must not overwrite their custom description/embedding.
    """
    from api.config import get_settings

    monkeypatch.setenv("LMSTUDIO_EMBED_MODEL", "text-embedding-nomic-embed-text-v1.5")
    get_settings.cache_clear()

    target = _DEMO_SEED_COLLECTIONS[0]
    with Session(get_engine()) as session:
        collection = session.get(RAGCollectionRecord, target.collection_id)
        assert collection is not None
        collection.description = "Reviewer's custom note"
        collection.embedding_model = "custom-embed-model"
        # Strip the seed marker — simulates a reviewer claiming the row.
        policy = dict(collection.chunking_policy_json or {})
        policy.pop("owner_tag", None)
        collection.chunking_policy_json = policy
        session.commit()

    with Session(get_engine()) as session:
        ensure_default_rag_collections(session)
        refreshed = session.get(RAGCollectionRecord, target.collection_id)
        assert refreshed is not None
        assert refreshed.description == "Reviewer's custom note"
        assert refreshed.embedding_model == "custom-embed-model"


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


def test_delete_collection_cascades_documents_and_returns_404_after(
    client: TestClient,
) -> None:
    create = client.post(
        "/rag-collections",
        json={"name": "delete-cascade-test"},
    )
    assert create.status_code == 201
    collection_id = create.json()["id"]

    upload = client.post(
        f"/rag-collections/{collection_id}/documents",
        files={"file": ("hello.txt", b"hello world", "text/plain")},
    )
    assert upload.status_code == 201
    document_id = upload.json()["id"]

    delete = client.delete(f"/rag-collections/{collection_id}")
    assert delete.status_code == 200
    payload = delete.json()
    assert payload["deleted"] is True
    assert payload["document_count"] == 1
    assert payload["collection_id"] == collection_id

    after = client.get(f"/rag-collections/{collection_id}")
    assert after.status_code == 404
    after_doc = client.get(f"/rag-documents/{document_id}")
    assert after_doc.status_code == 404


def test_delete_collection_returns_404_when_missing(client: TestClient) -> None:
    response = client.delete("/rag-collections/does-not-exist")
    assert response.status_code == 404


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

    listed = json.loads(tools.list_collections())
    assert listed["ok"] is True
    seed_ids = {entry["id"] for entry in listed["collections"]}
    assert {spec.collection_id for spec in _DEMO_SEED_COLLECTIONS} <= seed_ids

    target = _DEMO_SEED_COLLECTIONS[0]
    # The seed is not graph-indexed in this unit test, so naive search returns a
    # well-formed (possibly empty) result; this asserts the tool wiring works.
    queried = json.loads(
        tools.search_collection(target.collection_id, "maintenance", mode="naive")
    )
    assert queried["ok"] is True
    assert queried["result"]["mode"] == "naive"
