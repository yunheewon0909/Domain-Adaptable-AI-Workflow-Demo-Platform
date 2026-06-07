from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.db import get_engine
from api.models import EvaluationQuestionRecord
from api.services.evaluation import qa_generator
from api.services.evaluation.qa_generator import (
    EvaluationGenerationError,
    generate_evaluation_set,
)
from api.services.rag.graph_index import index_collection


def _fake_extractor(chunk: str) -> dict:
    return {"entities": [{"name": "Pump", "type": "x", "description": "d"}], "relationships": []}


def _fake_generator(chunk: str, n: int) -> list[dict[str, str]]:
    return [
        {"question": f"What about {chunk[:10]!r}?", "answer": "an answer"}
        for _ in range(n)
    ]


def _seed_indexed_collection(client: TestClient, text: str = "Pump P-101 feeds Reactor.") -> str:
    coll = client.post("/rag-collections", json={"name": "KB"}).json()["id"]
    client.post(
        f"/rag-collections/{coll}/documents/text",
        json={"filename": "n.md", "content": text},
    )
    with Session(get_engine()) as session:
        index_collection(session, collection_id=coll, extractor=_fake_extractor)
    return coll


def test_generate_links_questions_to_source_chunks(client: TestClient) -> None:
    coll = _seed_indexed_collection(client)
    with Session(get_engine()) as session:
        result = generate_evaluation_set(
            session,
            collection_id=coll,
            name="My eval",
            questions_per_chunk=2,
            generator=_fake_generator,
        )
    assert result["question_count"] >= 1

    with Session(get_engine()) as session:
        questions = (
            session.query(EvaluationQuestionRecord)
            .filter_by(evaluation_set_id=result["evaluation_set_id"])
            .all()
        )
        assert questions
        assert all(q.source_chunk_id for q in questions), "every question links to a chunk"
        assert all(q.status == "pending" for q in questions)


def test_generate_deduplicates_questions(client: TestClient) -> None:
    coll = _seed_indexed_collection(client)

    def _dup_generator(chunk: str, n: int) -> list[dict[str, str]]:
        return [{"question": "Same question?", "answer": "a"} for _ in range(n)]

    with Session(get_engine()) as session:
        result = generate_evaluation_set(
            session, collection_id=coll, name="dup", generator=_dup_generator
        )
    # All identical → deduped to a single question.
    assert result["question_count"] == 1


def test_generate_raises_without_chunks(client: TestClient) -> None:
    coll = client.post("/rag-collections", json={"name": "empty"}).json()["id"]
    with Session(get_engine()) as session:
        try:
            generate_evaluation_set(session, collection_id=coll, name="x", generator=_fake_generator)
            assert False, "expected EvaluationGenerationError"
        except EvaluationGenerationError:
            pass


def test_malformed_llm_response_yields_no_questions() -> None:
    assert qa_generator._parse_qa_json("garbage") == []
    parsed = qa_generator._parse_qa_json('[{"question": "Long enough question?", "answer": "a"}]')
    assert parsed == [{"question": "Long enough question?", "answer": "a"}]


# --- endpoints + review workflow --------------------------------------
def test_endpoint_generate_and_review(client: TestClient, monkeypatch) -> None:
    coll = _seed_indexed_collection(client)
    monkeypatch.setattr(qa_generator, "runtime_question_generator", _fake_generator)

    resp = client.post(
        "/evaluation-sets/from-collection",
        json={"collection_id": coll, "name": "Eval", "questions_per_chunk": 1},
    )
    assert resp.status_code == 201, resp.text
    set_id = resp.json()["evaluation_set_id"]

    detail = client.get(f"/evaluation-sets/{set_id}").json()
    assert detail["question_count"] >= 1
    q_id = detail["questions"][0]["id"]

    # accept
    accepted = client.patch(f"/evaluation-questions/{q_id}", json={"status": "accepted"})
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"

    # edit (no explicit status -> becomes "edited")
    edited = client.patch(f"/evaluation-questions/{q_id}", json={"question": "Edited question?"})
    assert edited.json()["question"] == "Edited question?"
    assert edited.json()["status"] == "edited"

    # listing
    sets = client.get("/evaluation-sets").json()
    assert any(s["id"] == set_id for s in sets)


def test_endpoint_404s(client: TestClient) -> None:
    assert client.get("/evaluation-sets/missing").status_code == 404
    assert (
        client.patch("/evaluation-questions/missing", json={"status": "accepted"}).status_code
        == 404
    )
    assert (
        client.post(
            "/evaluation-sets/from-collection",
            json={"collection_id": "missing", "name": "x"},
        ).status_code
        == 404
    )
