"""Generate instruction_sft training rows from a RAG collection.

Pipeline:
1. Pull `text_preview` content from documents in the target collection.
2. Slice each document into reviewer-friendly chunks (no token-aware splitter
   needed because the upstream chunks are already trimmed to text_preview).
3. Ask the configured chat client to emit a strict JSON array of Q/A pairs
   for each chunk.
4. Reject malformed responses but keep going; the caller decides what to do
   with the per-chunk error report.

The generator is intentionally synchronous and does not commit anything to the
database; the FT service consumes the pairs and persists them via the existing
`create_dataset` / `create_dataset_version` / `add_dataset_rows` helpers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.llm import LLMClient, LLMClientError
from api.models import RAGCollectionRecord, RAGDocumentRecord


_DEFAULT_CHUNK_SIZE_CHARS = 1500
_DEFAULT_PAIRS_PER_CHUNK = 3
_MIN_CHUNK_CHARS = 120
_MIN_QUESTION_CHARS = 8
_MIN_ANSWER_CHARS = 4
_DEDUP_KEY_LENGTH = 80
_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


@dataclass
class GeneratedPair:
    instruction: str
    answer: str
    source_document_id: str
    source_filename: str | None


@dataclass
class ChunkError:
    document_id: str
    chunk_index: int
    reason: str


@dataclass
class GenerationResult:
    pairs: list[GeneratedPair] = field(default_factory=list)
    errors: list[ChunkError] = field(default_factory=list)
    chunk_count: int = 0


def _chunk_text(text: str, *, chunk_chars: int) -> list[str]:
    cleaned = text.strip()
    if len(cleaned) <= chunk_chars:
        return [cleaned] if cleaned else []
    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(start + chunk_chars, len(cleaned))
        # try to break on a paragraph or sentence boundary near `end`
        if end < len(cleaned):
            window = cleaned[start:end]
            for sep in ("\n\n", ". ", "? ", "! ", "\n"):
                idx = window.rfind(sep)
                if idx >= chunk_chars // 2:
                    end = start + idx + len(sep)
                    break
        chunk = cleaned[start:end].strip()
        if len(chunk) >= _MIN_CHUNK_CHARS:
            chunks.append(chunk)
        start = end
    return chunks


def _build_prompt(
    chunk: str, *, pairs_per_chunk: int, retry: bool = False
) -> tuple[str, str]:
    if retry:
        # Stricter retry prompt: explicit JSON-only contract + sample shape.
        instruction = (
            "Your previous reply was not valid JSON. Emit ONLY a JSON array of "
            f"exactly {pairs_per_chunk} objects, no prose, no markdown, no code "
            'fences. Example shape: '
            '[{"question": "...", "answer": "..."}, ...]. '
            "Each question and answer must be self-contained and grounded in the "
            "CONTEXT below."
        )
    else:
        instruction = (
            f"You are creating fine-tuning data. Read the CONTEXT and emit exactly "
            f"{pairs_per_chunk} self-contained question/answer pairs grounded in it. "
            "Return ONLY a JSON array of objects shaped "
            '{"question": "...", "answer": "..."}. No commentary, no markdown.'
        )
    return instruction, chunk


def _dedup_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())[:_DEDUP_KEY_LENGTH]


def _parse_pairs(raw_text: str, *, max_pairs: int) -> tuple[list[dict[str, str]], str | None]:
    text = raw_text.strip()
    if not text:
        return [], "empty response"

    match = _JSON_ARRAY_RE.search(text)
    candidate = match.group(0) if match else text

    try:
        decoded = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return [], f"json decode failed: {exc}"

    if not isinstance(decoded, list):
        return [], f"expected JSON array, got {type(decoded).__name__}"

    pairs: list[dict[str, str]] = []
    for item in decoded[:max_pairs]:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or item.get("instruction") or "").strip()
        answer = str(item.get("answer") or item.get("output") or "").strip()
        if len(question) < _MIN_QUESTION_CHARS or len(answer) < _MIN_ANSWER_CHARS:
            continue
        pairs.append({"question": question, "answer": answer})
    if not pairs:
        return [], "no valid pairs in response"
    return pairs, None


def generate_pairs_from_collection(
    session: Session,
    *,
    collection_id: str,
    llm_client: LLMClient,
    max_chunks: int = 50,
    pairs_per_chunk: int = _DEFAULT_PAIRS_PER_CHUNK,
    chunk_chars: int = _DEFAULT_CHUNK_SIZE_CHARS,
    chat_model: str | None = None,
) -> GenerationResult:
    collection = session.get(RAGCollectionRecord, collection_id)
    if collection is None:
        raise KeyError(collection_id)

    documents = list(
        session.scalars(
            select(RAGDocumentRecord)
            .where(RAGDocumentRecord.collection_id == collection_id)
            .order_by(RAGDocumentRecord.created_at.asc())
        ).all()
    )

    result = GenerationResult()
    if not documents:
        return result

    seen_questions: set[str] = set()

    for document in documents:
        metadata = document.metadata_json or {}
        text = str(metadata.get("text_preview") or "").strip()
        if not text:
            continue
        chunks = _chunk_text(text, chunk_chars=chunk_chars)
        for chunk_index, chunk in enumerate(chunks):
            if result.chunk_count >= max_chunks:
                return result
            result.chunk_count += 1

            pairs, error = _request_pairs(
                llm_client=llm_client,
                chunk=chunk,
                pairs_per_chunk=pairs_per_chunk,
                chat_model=chat_model,
            )
            if error:
                result.errors.append(
                    ChunkError(
                        document_id=document.id,
                        chunk_index=chunk_index,
                        reason=error,
                    )
                )
                continue
            for pair in pairs:
                key = _dedup_key(pair["question"])
                if key in seen_questions:
                    continue
                seen_questions.add(key)
                result.pairs.append(
                    GeneratedPair(
                        instruction=pair["question"],
                        answer=pair["answer"],
                        source_document_id=document.id,
                        source_filename=document.filename,
                    )
                )
    return result


def _request_pairs(
    *,
    llm_client: LLMClient,
    chunk: str,
    pairs_per_chunk: int,
    chat_model: str | None,
) -> tuple[list[dict[str, str]], str | None]:
    """Call the LLM with one retry on parse failure (stricter prompt)."""
    last_error: str | None = None
    for retry in (False, True):
        instruction, context = _build_prompt(
            chunk, pairs_per_chunk=pairs_per_chunk, retry=retry
        )
        try:
            chat_result = llm_client.generate_answer(
                question=instruction,
                context=context,
                model=chat_model,
                temperature=0,
                max_tokens=4096,  # Qwen reasoning models need headroom for think+answer
            )
        except LLMClientError as exc:
            return [], f"llm call failed: {exc}"
        pairs, parse_error = _parse_pairs(
            chat_result.answer, max_pairs=pairs_per_chunk
        )
        if pairs:
            return pairs, None
        last_error = parse_error
    return [], last_error


def build_dataset_rows(
    pairs: list[GeneratedPair],
    *,
    collection_id: str,
) -> list[dict[str, Any]]:
    """Convert generated pairs into the row shape accepted by add_dataset_rows."""
    return [
        {
            "split": "train",
            "input_json": {"instruction": pair.instruction, "input": ""},
            "target_json": {"output": pair.answer},
            "metadata_json": {
                "source": "rag_collection",
                "rag_collection_id": collection_id,
                "rag_document_id": pair.source_document_id,
                "rag_document_filename": pair.source_filename,
            },
        }
        for pair in pairs
    ]
