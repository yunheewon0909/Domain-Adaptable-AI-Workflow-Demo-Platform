from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.db import get_engine
from api.dependencies import get_llm_client
from api.llm import ChatResult, LLMClientError
from api.main import app
from api.models import RAGCollectionRecord, RAGDocumentRecord


class _FakeChat:
    def __init__(self, responses: list[str | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def generate_answer(
        self,
        *,
        question: str,
        context: str,
        model: str | None = None,
        temperature: float = 0,
        max_tokens: int | None = None,
    ) -> ChatResult:
        self.calls.append((question, context))
        if not self._responses:
            raise LLMClientError("no more fake responses queued")
        payload = self._responses.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return ChatResult(answer=payload, model=model or "fake", used_fallback=False)


def _seed_collection(
    *,
    collection_id: str = "rag-collection-from-rag-test",
    text: str = "Solar maintenance requires monthly panel cleaning and quarterly inverter checks.",
) -> None:
    with Session(get_engine()) as session:
        session.add(
            RAGCollectionRecord(
                id=collection_id,
                name="From-RAG smoke",
                embedding_model="ignored",
                chunking_policy_json={"chunk_size": 256, "chunk_overlap": 0},
            )
        )
        session.flush()
        session.add(
            RAGDocumentRecord(
                id=f"{collection_id}-doc-1",
                collection_id=collection_id,
                filename="ops.md",
                mime_type="text/markdown",
                source_type="upload",
                metadata_json={"text_preview": text, "size_bytes": len(text.encode("utf-8"))},
            )
        )
        session.commit()


def test_from_rag_endpoint_builds_dataset_from_generated_qa_pairs(
    client: TestClient,
) -> None:
    _seed_collection()
    fake = _FakeChat(
        responses=[
            json.dumps(
                [
                    {"question": "How often should panels be cleaned?", "answer": "Monthly."},
                    {"question": "How often are inverters checked?", "answer": "Quarterly."},
                ]
            )
        ]
    )
    app.dependency_overrides[get_llm_client] = lambda: fake

    try:
        response = client.post(
            "/ft-datasets/from-rag-collection",
            json={
                "rag_collection_id": "rag-collection-from-rag-test",
                "dataset_name": "From RAG smoke",
                "max_chunks": 5,
                "pairs_per_chunk": 2,
                "chunk_chars": 2000,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["row_count"] == 2
    assert body["chunk_count"] == 1
    assert body["rejected_chunk_count"] == 0

    dataset = client.get(f"/ft-datasets/{body['dataset_id']}")
    assert dataset.status_code == 200
    versions = dataset.json()["versions"]
    assert len(versions) == 1
    rows = client.get(f"/ft-dataset-versions/{body['dataset_version_id']}/rows")
    payloads = rows.json()
    assert {row["input_json"]["instruction"] for row in payloads} == {
        "How often should panels be cleaned?",
        "How often are inverters checked?",
    }
    assert all(row["target_json"]["output"] for row in payloads)
    assert all(
        row["metadata_json"]["source"] == "rag_collection"
        for row in payloads
    )


def test_from_rag_endpoint_rejects_unknown_collection(client: TestClient) -> None:
    app.dependency_overrides[get_llm_client] = lambda: _FakeChat(responses=[])
    try:
        response = client.post(
            "/ft-datasets/from-rag-collection",
            json={
                "rag_collection_id": "missing",
                "dataset_name": "x",
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404


def test_from_rag_endpoint_returns_422_when_all_chunks_fail(
    client: TestClient,
) -> None:
    _seed_collection(collection_id="rag-collection-from-rag-test-2")
    # Two non-JSON responses — first attempt + stricter retry both fail.
    fake = _FakeChat(responses=["this is not JSON", "still not JSON"])
    app.dependency_overrides[get_llm_client] = lambda: fake
    try:
        response = client.post(
            "/ft-datasets/from-rag-collection",
            json={
                "rag_collection_id": "rag-collection-from-rag-test-2",
                "dataset_name": "y",
                "pairs_per_chunk": 2,
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422
    body = response.json()["detail"]
    assert body["chunk_count"] == 1
    assert len(body["errors"]) == 1
    assert "json decode failed" in body["errors"][0]["reason"]
    # Retry path called the LLM twice for the single chunk
    assert len(fake.calls) == 2


def test_from_rag_endpoint_retries_once_on_parse_failure(client: TestClient) -> None:
    _seed_collection(collection_id="rag-collection-from-rag-test-retry")
    # First reply is garbage; retry returns valid JSON.
    fake = _FakeChat(
        responses=[
            "not JSON at all",
            json.dumps(
                [
                    {"question": "When are inverters checked?", "answer": "Quarterly."},
                ]
            ),
        ]
    )
    app.dependency_overrides[get_llm_client] = lambda: fake
    try:
        response = client.post(
            "/ft-datasets/from-rag-collection",
            json={
                "rag_collection_id": "rag-collection-from-rag-test-retry",
                "dataset_name": "retry test",
                "pairs_per_chunk": 1,
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["row_count"] == 1
    assert body["rejected_chunk_count"] == 0
    assert len(fake.calls) == 2


def test_from_rag_endpoint_deduplicates_near_identical_questions(
    client: TestClient,
) -> None:
    _seed_collection(
        collection_id="rag-collection-from-rag-test-dedup",
        text=(
            "First chunk talks about panels. " * 30
            + "\n\n"
            + "Second chunk talks about inverters. " * 30
        ),
    )
    duplicates = json.dumps(
        [
            {"question": "How often clean panels?", "answer": "Monthly."},
            {"question": "How OFTEN  clean panels?", "answer": "Monthly clean."},
        ]
    )
    fake = _FakeChat(responses=[duplicates, duplicates])
    app.dependency_overrides[get_llm_client] = lambda: fake
    try:
        response = client.post(
            "/ft-datasets/from-rag-collection",
            json={
                "rag_collection_id": "rag-collection-from-rag-test-dedup",
                "dataset_name": "dedup test",
                "pairs_per_chunk": 2,
                "chunk_chars": 600,
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 201, response.text
    body = response.json()
    # Two chunks emitted, each with 2 near-identical questions; dedup keeps 1.
    assert body["chunk_count"] >= 2
    assert body["row_count"] == 1
