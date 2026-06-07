from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.db import get_engine
from api.models import (
    RAGChunkRecord,
    RAGCommunityRecord,
    RAGEntityChunkRecord,
    RAGEntityRecord,
    RAGQueryTraceRecord,
    RAGRelationshipRecord,
)
from api.services.rag import graph_index
from api.services.rag.graph_index import chunk_text, index_collection
from api.services.rag.graph_retrieval import query_collection


# A deterministic fake extractor: returns entities/relationships based on
# keywords present in the chunk, so indexing is fully offline.
def _fake_extractor(chunk: str) -> dict:
    lower = chunk.lower()
    entities = []
    relationships = []
    if "pump" in lower:
        entities.append({"name": "Pump P-101", "type": "equipment", "description": "feed pump"})
    if "reactor" in lower:
        entities.append({"name": "Reactor R-200", "type": "equipment", "description": "main reactor"})
    if "pump" in lower and "reactor" in lower:
        relationships.append(
            {"source": "Pump P-101", "target": "Reactor R-200", "description": "feeds"}
        )
    return {"entities": entities, "relationships": relationships}


def _seed_collection_with_doc(client: TestClient, text: str) -> str:
    coll = client.post("/rag-collections", json={"name": "KB"}).json()["id"]
    client.post(
        f"/rag-collections/{coll}/documents/text",
        json={"filename": "notes.md", "content": text},
    )
    return coll


# --- chunking ----------------------------------------------------------
def test_chunk_text_empty_returns_empty() -> None:
    assert chunk_text("", chunk_size=100, overlap=10) == []


def test_chunk_text_splits_long_text() -> None:
    text = "word " * 400  # 2000 chars
    chunks = chunk_text(text, chunk_size=500, overlap=50)
    assert len(chunks) > 1
    assert all(c.strip() for c in chunks)


# --- indexing ----------------------------------------------------------
def test_index_collection_creates_chunks_entities_relationships(client: TestClient) -> None:
    coll = _seed_collection_with_doc(
        client, "Pump P-101 feeds Reactor R-200 in the plant."
    )
    with Session(get_engine()) as session:
        stats = index_collection(session, collection_id=coll, extractor=_fake_extractor)

    assert stats["chunks"] >= 1
    assert stats["entities"] == 2
    assert stats["relationships"] == 1
    assert stats["communities"] >= 1

    with Session(get_engine()) as session:
        entities = session.query(RAGEntityRecord).filter_by(collection_id=coll).all()
        names = sorted(e.name for e in entities)
        assert names == ["Pump P-101", "Reactor R-200"]
        # entity→chunk provenance recorded
        assert session.query(RAGEntityChunkRecord).count() >= 2
        # relationship + community persisted
        assert session.query(RAGRelationshipRecord).filter_by(collection_id=coll).count() == 1
        assert session.query(RAGCommunityRecord).filter_by(collection_id=coll).count() >= 1


def test_index_collection_is_idempotent(client: TestClient) -> None:
    coll = _seed_collection_with_doc(client, "Pump P-101 feeds Reactor R-200.")
    with Session(get_engine()) as session:
        index_collection(session, collection_id=coll, extractor=_fake_extractor)
        index_collection(session, collection_id=coll, extractor=_fake_extractor)
    with Session(get_engine()) as session:
        # Reindex must not duplicate entities.
        assert session.query(RAGEntityRecord).filter_by(collection_id=coll).count() == 2
        assert session.query(RAGChunkRecord).filter_by(collection_id=coll).count() >= 1


def test_extractor_handles_malformed_llm_json() -> None:
    assert graph_index._parse_graph_json("not json at all") == {
        "entities": [],
        "relationships": [],
    }
    assert graph_index._parse_graph_json(
        '```json\n{"entities": [{"name": "X"}], "relationships": []}\n```'
    ) == {"entities": [{"name": "X"}], "relationships": []}


# --- retrieval + trace -------------------------------------------------
def test_local_retrieval_returns_traced_evidence(client: TestClient) -> None:
    coll = _seed_collection_with_doc(
        client, "Pump P-101 feeds Reactor R-200 which produces output."
    )
    with Session(get_engine()) as session:
        index_collection(session, collection_id=coll, extractor=_fake_extractor)
        result = query_collection(
            session, collection_id=coll, query="What does pump P-101 feed?", mode="local"
        )

    assert result["mode"] == "local"
    assert result["trace_id"]
    assert result["chunks"], "local search should return chunk evidence"
    # entity seeding matched 'pump'
    assert any(e["name"] == "Pump P-101" for e in result["entities"])
    # trace shape has the required evidence fields
    chunk0 = result["chunks"][0]
    assert {"chunk_id", "document_id", "score", "excerpt"} <= set(chunk0)

    with Session(get_engine()) as session:
        trace = session.query(RAGQueryTraceRecord).filter_by(collection_id=coll).one()
        assert trace.mode == "local"
        assert "chunks" in trace.results_json


def test_global_retrieval_uses_community_summaries(client: TestClient) -> None:
    coll = _seed_collection_with_doc(client, "Pump P-101 feeds Reactor R-200.")
    with Session(get_engine()) as session:
        index_collection(session, collection_id=coll, extractor=_fake_extractor)
        result = query_collection(
            session, collection_id=coll, query="overview", mode="global"
        )
    assert result["mode"] == "global"
    assert "communities" in result


# --- endpoints ---------------------------------------------------------
def test_index_endpoint_enqueues_job(client: TestClient) -> None:
    coll = _seed_collection_with_doc(client, "Pump P-101 feeds Reactor R-200.")
    resp = client.post(f"/rag-collections/{coll}/index")
    assert resp.status_code == 202
    job = resp.json()["job"]
    assert job["type"] == "rag_index_collection"
    assert job["status"] == "queued"


def test_index_endpoint_404_for_missing_collection(client: TestClient) -> None:
    assert client.post("/rag-collections/nope/index").status_code == 404


def test_query_endpoint_runs_after_indexing(client: TestClient) -> None:
    coll = _seed_collection_with_doc(client, "Pump P-101 feeds Reactor R-200.")
    with Session(get_engine()) as session:
        index_collection(session, collection_id=coll, extractor=_fake_extractor)
    resp = client.post(
        f"/rag-collections/{coll}/query",
        json={"query": "pump", "mode": "naive", "top_k": 3},
    )
    assert resp.status_code == 200
    assert resp.json()["mode"] == "naive"


def test_subgraph_endpoint_returns_nodes_and_edges(client: TestClient) -> None:
    coll = _seed_collection_with_doc(client, "Pump P-101 feeds Reactor R-200.")
    with Session(get_engine()) as session:
        index_collection(session, collection_id=coll, extractor=_fake_extractor)
    resp = client.get(f"/rag-collections/{coll}/subgraph")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["nodes"]) == 2
    assert len(body["edges"]) == 1
