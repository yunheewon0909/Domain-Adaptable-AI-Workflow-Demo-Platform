"""RAG evaluation runs + reports (ADR 0008 / migration Phase 7).

Executes each (non-rejected) question in an evaluation set through graph
retrieval + answer generation, scores groundedness and source coverage against
the stored retrieval evidence, and aggregates a report. The answer generator is
injectable so runs are testable offline.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.llm import LLMClientError
from api.models import (
    EvaluationQuestionRecord,
    EvaluationResultRecord,
    EvaluationRunRecord,
    EvaluationSetRecord,
    RAGChunkRecord,
    RAGCommunityRecord,
    RAGDocumentRecord,
    RAGEntityChunkRecord,
    RAGEntityRecord,
    RAGRelationshipRecord,
)
from api.services.rag.graph_retrieval import query_collection
from api.services.runtime import get_chat_runtime

# An answerer maps (question, context) -> answer text.
Answerer = Callable[[str, str], str]

_GROUNDEDNESS_THRESHOLD = 0.3


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _content_tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]{4,}", (text or "").lower())}


def _groundedness(answer: str, context: str) -> float:
    """Fraction of the answer's content tokens that appear in the context."""
    answer_tokens = _content_tokens(answer)
    if not answer_tokens:
        return 0.0
    context_tokens = _content_tokens(context)
    grounded = answer_tokens & context_tokens
    return round(len(grounded) / len(answer_tokens), 4)


def runtime_answerer(question: str, context: str) -> str:
    try:
        result = get_chat_runtime().generate_answer(
            question=question, context=context, temperature=0, max_tokens=512
        )
    except LLMClientError:
        return ""
    return result.answer


def create_run(
    session: Session, *, evaluation_set_id: str, mode: str = "local"
) -> EvaluationRunRecord:
    eval_set = session.get(EvaluationSetRecord, evaluation_set_id)
    if eval_set is None:
        raise KeyError(evaluation_set_id)
    run = EvaluationRunRecord(
        id=_new_id("eval-run"),
        evaluation_set_id=evaluation_set_id,
        collection_id=eval_set.collection_id,
        mode=mode,
        status="queued",
    )
    session.add(run)
    session.commit()
    return run


def _graph_stats(session: Session, collection_id: str) -> dict[str, Any]:
    def count(model: Any) -> int:
        return int(
            session.scalar(
                select(func.count()).select_from(model).where(
                    model.collection_id == collection_id
                )
            )
            or 0
        )

    chunk_total = count(RAGChunkRecord)
    chunk_ids = set(
        session.scalars(
            select(RAGChunkRecord.id).where(
                RAGChunkRecord.collection_id == collection_id
            )
        ).all()
    )
    linked_chunk_ids = set(
        session.scalars(
            select(RAGEntityChunkRecord.chunk_id).where(
                RAGEntityChunkRecord.chunk_id.in_(chunk_ids)
            )
        ).all()
    ) if chunk_ids else set()
    orphan_chunks = len(chunk_ids - linked_chunk_ids)
    documents = int(
        session.scalar(
            select(func.count()).select_from(RAGDocumentRecord).where(
                RAGDocumentRecord.collection_id == collection_id
            )
        )
        or 0
    )
    return {
        "documents": documents,
        "chunks": chunk_total,
        "entities": count(RAGEntityRecord),
        "relationships": count(RAGRelationshipRecord),
        "communities": count(RAGCommunityRecord),
        "orphan_chunks": orphan_chunks,
        "indexed": chunk_total > 0,
    }


def run_evaluation(
    session: Session, *, run_id: str, answerer: Answerer | None = None
) -> dict[str, Any]:
    run = session.get(EvaluationRunRecord, run_id)
    if run is None:
        raise KeyError(run_id)
    answerer = answerer or runtime_answerer

    run.status = "running"
    session.commit()

    questions = list(
        session.scalars(
            select(EvaluationQuestionRecord).where(
                EvaluationQuestionRecord.evaluation_set_id == run.evaluation_set_id,
                EvaluationQuestionRecord.status != "rejected",
            )
        ).all()
    )

    results: list[EvaluationResultRecord] = []
    coverage_scored = 0
    coverage_hits = 0
    for q in questions:
        retrieval = query_collection(
            session,
            collection_id=run.collection_id,
            query=q.question,
            mode=run.mode,
            top_k=5,
        )
        context = retrieval.get("context", "")
        chunk_ids = [c["chunk_id"] for c in retrieval.get("chunks", [])]
        entity_ids = [e["entity_id"] for e in retrieval.get("entities", [])]
        answer = answerer(q.question, context)
        grounded = _groundedness(answer, context)

        coverage = 0.0
        if q.source_chunk_id:
            coverage_scored += 1
            if q.source_chunk_id in chunk_ids:
                coverage = 1.0
                coverage_hits += 1
        hallucination = bool(answer) and grounded < _GROUNDEDNESS_THRESHOLD

        results.append(
            EvaluationResultRecord(
                id=_new_id("eval-res"),
                run_id=run.id,
                question_id=q.id,
                question=q.question,
                generated_answer=answer or None,
                retrieved_chunk_ids_json=chunk_ids,
                retrieved_entity_ids_json=entity_ids,
                groundedness=grounded,
                source_coverage=coverage,
                hallucination=hallucination,
                notes=(
                    "answer not grounded in retrieved evidence"
                    if hallucination
                    else None
                ),
            )
        )
    session.add_all(results)

    n = len(results)
    avg_groundedness = round(sum(r.groundedness for r in results) / n, 4) if n else 0.0
    hallucination_rate = round(sum(1 for r in results if r.hallucination) / n, 4) if n else 0.0
    source_coverage = round(coverage_hits / coverage_scored, 4) if coverage_scored else None

    report = {
        "question_count": n,
        "answer_quality": {
            "avg_groundedness": avg_groundedness,
            "hallucination_rate": hallucination_rate,
        },
        "retrieval_quality": {
            "source_coverage": source_coverage,
            "questions_with_known_source": coverage_scored,
        },
        "collection_health": _graph_stats(session, run.collection_id),
    }
    run.question_count = n
    run.report_json = report
    run.status = "succeeded"
    run.finished_at = datetime.now(timezone.utc)
    session.commit()
    return report
