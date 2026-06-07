"""Evaluation testset generation from RAG chunks (ADR 0008).

The former fine-tuning Q/A generator, repurposed: it produces reviewable
``evaluation_questions`` grounded in (and linked to) the collection's
``rag_chunks``. The LLM call is injectable so generation is testable offline.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.llm import LLMClientError
from api.models import (
    EvaluationQuestionRecord,
    EvaluationSetRecord,
    RAGChunkRecord,
    RAGCollectionRecord,
)
from api.services.runtime import get_chat_runtime

# A question generator maps (chunk_text, n) to a list of {"question","answer"}.
QuestionGenerator = Callable[[str, int], list[dict[str, str]]]


class EvaluationGenerationError(RuntimeError):
    pass


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _normalize_question(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()[:80]


_GEN_INSTRUCTION = (
    "From the CONTEXT, write {n} self-contained question/answer pairs that test "
    "comprehension of the content. Respond with ONLY a JSON array "
    '[{{"question": str, "answer": str}}]. No prose, no markdown.'
)


def _parse_qa_json(raw: str) -> list[dict[str, str]]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    pairs: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        answer = str(item.get("answer") or "").strip()
        if len(question) >= 8:
            pairs.append({"question": question, "answer": answer})
    return pairs


def runtime_question_generator(chunk: str, n: int) -> list[dict[str, str]]:
    """Default generator: ask the chat runtime for Q/A JSON. Empty on failure."""
    try:
        result = get_chat_runtime().generate_answer(
            question=_GEN_INSTRUCTION.format(n=n),
            context=chunk,
            temperature=0,
            max_tokens=2048,
        )
    except LLMClientError:
        return []
    return _parse_qa_json(result.answer)


def generate_evaluation_set(
    session: Session,
    *,
    collection_id: str,
    name: str,
    description: str | None = None,
    questions_per_chunk: int = 2,
    max_chunks: int = 50,
    generator: QuestionGenerator | None = None,
) -> dict[str, Any]:
    """Create an evaluation set with reviewable questions from the collection's chunks."""
    if session.get(RAGCollectionRecord, collection_id) is None:
        raise KeyError(collection_id)
    generator = generator or runtime_question_generator
    questions_per_chunk = max(1, min(int(questions_per_chunk), 10))
    max_chunks = max(1, min(int(max_chunks), 500))

    chunks = list(
        session.scalars(
            select(RAGChunkRecord)
            .where(RAGChunkRecord.collection_id == collection_id)
            .order_by(RAGChunkRecord.document_id, RAGChunkRecord.ordinal)
            .limit(max_chunks)
        ).all()
    )
    if not chunks:
        raise EvaluationGenerationError(
            "collection has no chunks; index the collection before generating an "
            "evaluation set"
        )

    eval_set = EvaluationSetRecord(
        id=_new_id("eval-set"),
        collection_id=collection_id,
        name=name.strip() or "Evaluation set",
        description=(description or None),
    )
    session.add(eval_set)
    session.flush()

    seen: set[str] = set()
    created: list[EvaluationQuestionRecord] = []
    for chunk in chunks:
        for pair in generator(chunk.text, questions_per_chunk):
            key = _normalize_question(pair.get("question", ""))
            if not key or key in seen:
                continue
            seen.add(key)
            created.append(
                EvaluationQuestionRecord(
                    id=_new_id("eval-q"),
                    evaluation_set_id=eval_set.id,
                    question=pair["question"],
                    answer=pair.get("answer") or None,
                    source_chunk_id=chunk.id,
                )
            )
    session.add_all(created)
    eval_set.question_count = len(created)
    session.commit()

    return {
        "evaluation_set_id": eval_set.id,
        "name": eval_set.name,
        "collection_id": collection_id,
        "question_count": len(created),
        "chunks_used": len(chunks),
    }
