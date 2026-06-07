"""Evaluation testset generation + review endpoints (ADR 0008)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from api.db import get_engine
from api.models import EvaluationResultRecord, EvaluationRunRecord
from api.services.jobs import create_job, serialize_job_summary
from api.services.evaluation.qa_generator import (
    EvaluationGenerationError,
    generate_evaluation_set,
)
from api.services.evaluation.runner import create_run
from api.services.evaluation.service import (
    QUESTION_STATUSES,
    get_set,
    list_sets,
    update_question,
)
from api.services.rag.graph_retrieval import MODES
from sqlalchemy import select

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


class CreateEvaluationRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evaluation_set_id: str = Field(min_length=1)
    mode: str = Field(default="local")


def _serialize_run(run: EvaluationRunRecord) -> dict[str, Any]:
    return {
        "id": run.id,
        "evaluation_set_id": run.evaluation_set_id,
        "collection_id": run.collection_id,
        "mode": run.mode,
        "status": run.status,
        "question_count": run.question_count,
        "report": run.report_json,
        "error": run.error,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


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


@router.post("/evaluation-runs", status_code=202)
def create_evaluation_run(request: CreateEvaluationRunRequest) -> dict[str, Any]:
    if request.mode not in MODES:
        raise HTTPException(
            status_code=400, detail=f"mode must be one of {sorted(MODES)}"
        )
    with Session(get_engine()) as session:
        try:
            run = create_run(
                session,
                evaluation_set_id=request.evaluation_set_id,
                mode=request.mode,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="evaluation set not found"
            ) from exc
        job = create_job(
            session, job_type="evaluation_run", payload_json={"run_id": run.id}
        )
        return {"run": _serialize_run(run), "job": serialize_job_summary(job)}


@router.get("/evaluation-runs/{run_id}")
def get_evaluation_run(run_id: str) -> dict[str, Any]:
    with Session(get_engine()) as session:
        run = session.get(EvaluationRunRecord, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="evaluation run not found")
        return _serialize_run(run)


@router.get("/evaluation-runs/{run_id}/report")
def get_evaluation_report(run_id: str) -> dict[str, Any]:
    with Session(get_engine()) as session:
        run = session.get(EvaluationRunRecord, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="evaluation run not found")
        results = session.scalars(
            select(EvaluationResultRecord)
            .where(EvaluationResultRecord.run_id == run_id)
            .order_by(EvaluationResultRecord.created_at.asc())
        ).all()
        return {
            "run": _serialize_run(run),
            "report": run.report_json,
            "results": [
                {
                    "question_id": r.question_id,
                    "question": r.question,
                    "generated_answer": r.generated_answer,
                    "retrieved_chunk_ids": r.retrieved_chunk_ids_json,
                    "retrieved_entity_ids": r.retrieved_entity_ids_json,
                    "groundedness": r.groundedness,
                    "source_coverage": r.source_coverage,
                    "hallucination": r.hallucination,
                    "notes": r.notes,
                }
                for r in results
            ],
        }
