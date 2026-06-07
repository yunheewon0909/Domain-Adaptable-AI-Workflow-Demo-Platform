from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.db import get_engine
from api.models import EvaluationResultRecord
from api.services.evaluation.qa_generator import generate_evaluation_set
from api.services.evaluation.runner import (
    _groundedness,
    create_run,
    run_evaluation,
)
from api.services.rag.graph_index import index_collection


def _fake_extractor(chunk: str) -> dict:
    return {
        "entities": [{"name": "Pump P-101", "type": "equipment", "description": "feed pump"}],
        "relationships": [],
    }


def _fake_qgen(chunk: str, n: int) -> list[dict[str, str]]:
    return [{"question": "What is pump P-101?", "answer": "a feed pump"}]


def _grounded_answerer(question: str, context: str) -> str:
    # Echo words from the context so groundedness is high.
    return " ".join(context.split()[:20]) or "pump"


def _hallucinating_answerer(question: str, context: str) -> str:
    return "completely unrelated zebra elephant spaceship narwhal"


def _setup_run_mode(client: TestClient, answerer, mode: str = "local") -> dict:
    coll = client.post("/rag-collections", json={"name": "KB"}).json()["id"]
    client.post(
        f"/rag-collections/{coll}/documents/text",
        json={"filename": "n.md", "content": "Pump P-101 feeds the main reactor unit."},
    )
    with Session(get_engine()) as session:
        index_collection(session, collection_id=coll, extractor=_fake_extractor)
        gen = generate_evaluation_set(
            session, collection_id=coll, name="eval", generator=_fake_qgen
        )
        run = create_run(session, evaluation_set_id=gen["evaluation_set_id"], mode=mode)
        report = run_evaluation(session, run_id=run.id, answerer=answerer)
        run_id = run.id
    return {"collection_id": coll, "run_id": run_id, "report": report}


def _setup_run(client: TestClient, answerer) -> dict:
    return _setup_run_mode(client, answerer, mode="local")


# --- scoring units -----------------------------------------------------
def test_groundedness_scoring() -> None:
    assert _groundedness("pump feeds reactor", "the pump feeds the reactor unit") == 1.0
    assert _groundedness("zebra spaceship", "the pump feeds the reactor") == 0.0
    assert _groundedness("", "anything") == 0.0


# --- run execution -----------------------------------------------------
def test_run_stores_per_question_results_and_report(client: TestClient) -> None:
    out = _setup_run(client, _grounded_answerer)
    report = out["report"]
    assert report["question_count"] >= 1
    assert "answer_quality" in report
    assert "retrieval_quality" in report
    assert "collection_health" in report
    # report includes graph stats
    health = report["collection_health"]
    assert health["entities"] >= 1
    assert health["indexed"] is True

    with Session(get_engine()) as session:
        results = (
            session.query(EvaluationResultRecord).filter_by(run_id=out["run_id"]).all()
        )
        assert results
        r = results[0]
        assert r.retrieved_chunk_ids_json  # retrieval trace recorded
        assert r.groundedness > 0  # grounded answerer


def test_hallucination_flagged_when_answer_ungrounded(client: TestClient) -> None:
    out = _setup_run(client, _hallucinating_answerer)
    assert out["report"]["answer_quality"]["hallucination_rate"] == 1.0


def test_source_coverage_reflects_known_source_chunk(client: TestClient) -> None:
    out = _setup_run(client, _grounded_answerer)
    # The generated question is linked to its source chunk; naive/local retrieval
    # over a single-chunk collection should retrieve it.
    coverage = out["report"]["retrieval_quality"]["source_coverage"]
    assert coverage == 1.0


# --- endpoints ---------------------------------------------------------
def test_run_endpoint_enqueues_job_and_report_fetchable(client: TestClient) -> None:
    coll = client.post("/rag-collections", json={"name": "KB"}).json()["id"]
    client.post(
        f"/rag-collections/{coll}/documents/text",
        json={"filename": "n.md", "content": "Pump P-101 feeds the reactor."},
    )
    with Session(get_engine()) as session:
        index_collection(session, collection_id=coll, extractor=_fake_extractor)
        gen = generate_evaluation_set(
            session, collection_id=coll, name="eval", generator=_fake_qgen
        )

    resp = client.post(
        "/evaluation-runs",
        json={"evaluation_set_id": gen["evaluation_set_id"], "mode": "local"},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["job"]["type"] == "evaluation_run"
    assert body["run"]["status"] == "queued"
    run_id = body["run"]["id"]

    # Execute inline (worker would do this) then fetch the report.
    with Session(get_engine()) as session:
        run_evaluation(session, run_id=run_id, answerer=_grounded_answerer)

    report_resp = client.get(f"/evaluation-runs/{run_id}/report")
    assert report_resp.status_code == 200
    rbody = report_resp.json()
    assert rbody["run"]["status"] == "succeeded"
    assert rbody["report"]["question_count"] >= 1
    assert isinstance(rbody["results"], list) and rbody["results"]


def test_run_marks_failed_when_answerer_raises(client: TestClient) -> None:
    """Regression: a raising run must end 'failed' with an error, not stuck 'running'."""
    import pytest as _pytest

    from api.models import EvaluationRunRecord

    coll = client.post("/rag-collections", json={"name": "KB"}).json()["id"]
    client.post(
        f"/rag-collections/{coll}/documents/text",
        json={"filename": "n.md", "content": "Pump P-101 feeds the reactor."},
    )

    def _boom(question: str, context: str) -> str:
        raise RuntimeError("answerer exploded")

    with Session(get_engine()) as session:
        index_collection(session, collection_id=coll, extractor=_fake_extractor)
        gen = generate_evaluation_set(
            session, collection_id=coll, name="eval", generator=_fake_qgen
        )
        run = create_run(session, evaluation_set_id=gen["evaluation_set_id"])
        run_id = run.id
        with _pytest.raises(RuntimeError, match="answerer exploded"):
            run_evaluation(session, run_id=run_id, answerer=_boom)

    with Session(get_engine()) as session:
        row = session.get(EvaluationRunRecord, run_id)
        assert row is not None
        assert row.status == "failed"
        assert "answerer exploded" in (row.error or "")
        assert row.finished_at is not None


def test_global_mode_coverage_is_not_applicable_not_zero(client: TestClient) -> None:
    """Regression: global mode returns no chunks, so source_coverage is None, not 0."""
    out = _setup_run_mode(client, _grounded_answerer, mode="global")
    rq = out["report"]["retrieval_quality"]
    assert rq["source_coverage"] is None
    assert rq["questions_with_known_source"] == 0


def test_report_includes_graph_density(client: TestClient) -> None:
    out = _setup_run(client, _grounded_answerer)
    assert "density" in out["report"]["collection_health"]


def test_run_endpoint_404_for_missing_set(client: TestClient) -> None:
    assert (
        client.post(
            "/evaluation-runs", json={"evaluation_set_id": "missing"}
        ).status_code
        == 404
    )
    assert client.get("/evaluation-runs/missing").status_code == 404
    assert client.get("/evaluation-runs/missing/report").status_code == 404
