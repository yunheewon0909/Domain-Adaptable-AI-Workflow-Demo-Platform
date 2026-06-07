"""Read/update helpers for evaluation sets + questions."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models import EvaluationQuestionRecord, EvaluationSetRecord

QUESTION_STATUSES = ("pending", "accepted", "rejected", "edited")


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def serialize_question(q: EvaluationQuestionRecord) -> dict[str, Any]:
    return {
        "id": q.id,
        "evaluation_set_id": q.evaluation_set_id,
        "question": q.question,
        "answer": q.answer,
        "status": q.status,
        "source_chunk_id": q.source_chunk_id,
        "source_entity_id": q.source_entity_id,
        "created_at": _iso(q.created_at),
        "updated_at": _iso(q.updated_at),
    }


def serialize_set(s: EvaluationSetRecord, *, with_questions: bool = False,
                  questions: list[EvaluationQuestionRecord] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": s.id,
        "collection_id": s.collection_id,
        "name": s.name,
        "description": s.description,
        "status": s.status,
        "question_count": s.question_count,
        "created_at": _iso(s.created_at),
        "updated_at": _iso(s.updated_at),
    }
    if with_questions:
        payload["questions"] = [serialize_question(q) for q in (questions or [])]
    return payload


def list_sets(session: Session) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(EvaluationSetRecord).order_by(EvaluationSetRecord.created_at.desc())
    ).all()
    return [serialize_set(s) for s in rows]


def get_set(session: Session, set_id: str) -> dict[str, Any] | None:
    s = session.get(EvaluationSetRecord, set_id)
    if s is None:
        return None
    questions = session.scalars(
        select(EvaluationQuestionRecord)
        .where(EvaluationQuestionRecord.evaluation_set_id == set_id)
        .order_by(EvaluationQuestionRecord.created_at.asc())
    ).all()
    return serialize_set(s, with_questions=True, questions=list(questions))


def update_question(
    session: Session,
    *,
    question_id: str,
    status: str | None = None,
    question: str | None = None,
    answer: str | None = None,
) -> dict[str, Any] | None:
    row = session.get(EvaluationQuestionRecord, question_id)
    if row is None:
        return None
    if status is not None:
        if status not in QUESTION_STATUSES:
            raise ValueError(f"status must be one of {QUESTION_STATUSES}")
        row.status = status
    if question is not None:
        row.question = question
        if status is None:
            row.status = "edited"
    if answer is not None:
        row.answer = answer
        if status is None:
            row.status = "edited"
    session.commit()
    return serialize_question(row)
