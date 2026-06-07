"""Evaluation testset generation + review endpoints (ADR 0008)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from api.db import get_engine
from api.services.evaluation.qa_generator import (
    EvaluationGenerationError,
    generate_evaluation_set,
)
from api.services.evaluation.service import (
    QUESTION_STATUSES,
    get_set,
    list_sets,
    update_question,
)

router = APIRouter(tags=["evaluation"])


class CreateEvaluationSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str | None = None
    questions_per_chunk: int = Field(default=2, ge=1, le=10)
    max_chunks: int = Field(default=50, ge=1, le=500)


class UpdateQuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str | None = None
    question: str | None = None
    answer: str | None = None


@router.post("/evaluation-sets/from-collection", status_code=201)
def create_evaluation_set(request: CreateEvaluationSetRequest) -> dict[str, Any]:
    with Session(get_engine()) as session:
        try:
            return generate_evaluation_set(
                session,
                collection_id=request.collection_id,
                name=request.name,
                description=request.description,
                questions_per_chunk=request.questions_per_chunk,
                max_chunks=request.max_chunks,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="RAG collection not found"
            ) from exc
        except EvaluationGenerationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/evaluation-sets")
def list_evaluation_sets() -> list[dict[str, Any]]:
    with Session(get_engine()) as session:
        return list_sets(session)


@router.get("/evaluation-sets/{set_id}")
def get_evaluation_set(set_id: str) -> dict[str, Any]:
    with Session(get_engine()) as session:
        result = get_set(session, set_id)
        if result is None:
            raise HTTPException(status_code=404, detail="evaluation set not found")
        return result


@router.patch("/evaluation-questions/{question_id}")
def patch_evaluation_question(
    question_id: str, request: UpdateQuestionRequest
) -> dict[str, Any]:
    if (
        request.status is None
        and request.question is None
        and request.answer is None
    ):
        raise HTTPException(
            status_code=400, detail="provide at least one of status/question/answer"
        )
    if request.status is not None and request.status not in QUESTION_STATUSES:
        raise HTTPException(
            status_code=400, detail=f"status must be one of {sorted(QUESTION_STATUSES)}"
        )
    with Session(get_engine()) as session:
        try:
            result = update_question(
                session,
                question_id=question_id,
                status=request.status,
                question=request.question,
                answer=request.answer,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if result is None:
            raise HTTPException(status_code=404, detail="question not found")
        return result
