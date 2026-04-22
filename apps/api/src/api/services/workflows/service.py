from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from api.llm import LLMClient, LLMClientError
from api.models import RAGCollectionRecord
from api.services.datasets.resolver import (
    DatasetNotFoundError,
    ResolvedDataset,
    resolve_dataset,
)
from api.services.model_registry import resolve_model_selection
from api.services.rag.embedding_client import EmbeddingClient
from api.services.rag.collections import preview_collection_retrieval
from api.services.rag.query import RAGIndexNotReadyError
from api.services.retrieval.service import build_grounding_context, retrieve_evidence
from api.services.workflows.catalog import WorkflowDefinition, get_workflow_definition
from api.services.workflows.contracts import (
    DRAFT_MODEL_BY_WORKFLOW_KEY,
    EvidenceItem,
    RESULT_MODEL_BY_WORKFLOW_KEY,
)
from api.services.workflows.profiles import get_profile


WORKFLOW_MAX_TOKENS = 512


class WorkflowExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkflowSourceSelection:
    source_type: str
    source_id: str
    source_label: str
    dataset: ResolvedDataset | None = None
    collection_id: str | None = None
    collection_description: str | None = None

    @property
    def dataset_key(self) -> str | None:
        return self.dataset.key if self.dataset is not None else None

    @property
    def rag_collection_id(self) -> str | None:
        return self.collection_id


def _rag_index_not_ready_result(
    *,
    workflow_key: str,
    dataset_key: str | None,
    user_prompt: str,
    db_path: str,
    source_meta: dict[str, Any],
    model_meta: dict[str, Any],
) -> dict[str, Any]:
    title = "RAG index is not ready"
    remediation = (
        "Run rag-ingest or enqueue RAG reindex before using retrieval-backed workflow."
    )
    docker_hint = "Docker demo can initialize the index with `docker compose exec -T api uv run rag-ingest`."
    meta = {
        "degraded": True,
        "rag_status": "not_ready",
        "db_path": db_path,
        "dataset_key": dataset_key,
        "prompt": user_prompt,
        "warnings": [title, remediation, docker_hint],
        **source_meta,
        **model_meta,
    }
    if workflow_key == "recommendation":
        return {
            "recommendations": [remediation, docker_hint],
            "rationale": (
                f"{title}. Retrieval-backed evidence is unavailable until the legacy index at {db_path} is initialized."
            ),
            "evidence": [],
            "meta": meta,
        }
    if workflow_key == "report_generator":
        return {
            "title": title,
            "executive_summary": (
                f"Workflow execution continued without retrieval evidence because the legacy RAG index at {db_path} is not initialized."
            ),
            "findings": [title, f"Legacy index path: {db_path}"],
            "actions": [remediation, docker_hint],
            "evidence": [],
            "meta": meta,
        }
    return {
        "summary": (
            f"Workflow execution continued without retrieval evidence because the legacy RAG index at {db_path} is not initialized."
        ),
        "key_points": [title, remediation, docker_hint],
        "evidence": [],
        "meta": meta,
    }


def _build_collection_context_unavailable_result(
    *,
    workflow_key: str,
    user_prompt: str,
    source_meta: dict[str, Any],
    model_meta: dict[str, Any],
    rag_status: str,
) -> dict[str, Any]:
    if rag_status == "empty":
        title = "RAG collection is empty"
        detail = "Upload at least one document with preview text before running this workflow."
    else:
        title = "No matching RAG collection context found"
        detail = "Try a broader query or upload documents that better match the reviewer request."

    meta = {
        "degraded": True,
        "rag_status": rag_status,
        "prompt": user_prompt,
        "warnings": [title, detail],
        **source_meta,
        **model_meta,
    }
    if workflow_key == "recommendation":
        return {
            "recommendations": [detail],
            "rationale": f"{title}. Workflow execution returned a graceful result without calling the LLM.",
            "evidence": [],
            "meta": meta,
        }
    if workflow_key == "report_generator":
        return {
            "title": title,
            "executive_summary": (
                f"Workflow execution continued without collection evidence because {title.lower()}."
            ),
            "findings": [title],
            "actions": [detail],
            "evidence": [],
            "meta": meta,
        }
    return {
        "summary": f"{title}. Workflow execution returned a graceful result without calling the LLM.",
        "key_points": [title, detail],
        "evidence": [],
        "meta": meta,
    }


def _resolve_workflow_source(
    session: Session,
    *,
    dataset_key: str | None,
    rag_collection_id: str | None,
) -> WorkflowSourceSelection:
    if dataset_key and rag_collection_id:
        raise WorkflowExecutionError(
            "provide either dataset_key or rag_collection_id, not both"
        )
    if rag_collection_id:
        collection = session.get(RAGCollectionRecord, rag_collection_id)
        if collection is None:
            raise WorkflowExecutionError("RAG collection not found")
        return WorkflowSourceSelection(
            source_type="rag_collection",
            source_id=collection.id,
            source_label=collection.name,
            collection_id=collection.id,
            collection_description=collection.description,
        )

    try:
        dataset = resolve_dataset(session, dataset_key)
    except DatasetNotFoundError as exc:
        raise WorkflowExecutionError(
            f"dataset not found: {dataset_key or 'active'}"
        ) from exc
    return WorkflowSourceSelection(
        source_type="dataset",
        source_id=dataset.key,
        source_label=dataset.title,
        dataset=dataset,
    )


def _resolve_workflow_model(
    session: Session, *, model_id: str | None
) -> dict[str, Any]:
    try:
        return resolve_model_selection(session, model_id=model_id)
    except KeyError as exc:
        raise WorkflowExecutionError("model not found") from exc
    except (LookupError, ValueError) as exc:
        raise WorkflowExecutionError(str(exc)) from exc


def _build_source_meta(source: WorkflowSourceSelection) -> dict[str, Any]:
    return {
        "dataset_key": source.dataset_key,
        "source_type": source.source_type,
        "source_id": source.source_id,
        "source_label": source.source_label,
        "rag_collection_id": source.rag_collection_id,
    }


def _build_model_meta(
    selected_model: dict[str, Any],
    *,
    selected_model_name: str | None = None,
    used_fallback: bool | None = None,
) -> dict[str, Any]:
    return {
        "model_id": selected_model.get("id"),
        "model_display_name": selected_model.get("display_name"),
        "selected_model": selected_model_name
        or selected_model.get("serving_model_name")
        or selected_model.get("ollama_model_name"),
        "used_fallback": used_fallback,
    }


def _derive_collection_evidence_title(filename: str) -> str:
    path = Path(filename)
    stem = path.stem or path.name or filename
    normalized = stem.replace("_", " ").replace("-", " ").strip()
    return normalized.title() or filename


def _retrieve_collection_evidence(
    session: Session,
    *,
    collection_id: str,
    query_text: str,
    top_k: int,
) -> tuple[list[Any], str]:
    preview = preview_collection_retrieval(
        session,
        collection_id=collection_id,
        query=query_text,
        top_k=top_k,
    )
    results = list(preview.get("results") or [])
    if not results:
        rag_status = "empty" if preview.get("document_count", 0) == 0 else "no_match"
        return [], rag_status
    evidence = [
        EvidenceItem(
            chunk_id=str(item.get("document_id") or f"collection-{index}"),
            source_path=str(item.get("filename") or "rag-collection-document"),
            title=_derive_collection_evidence_title(
                str(item.get("filename") or "rag-collection-document")
            ),
            text=str(item.get("excerpt") or "collection preview unavailable"),
            score=float(item.get("score") or 0.0),
        )
        for index, item in enumerate(results, start=1)
    ]
    return evidence, "ready"


def create_workflow_job_payload(
    session: Session,
    *,
    workflow_key: str,
    prompt: str,
    dataset_key: str | None,
    rag_collection_id: str | None = None,
    model_id: str | None = None,
    top_k: int,
) -> tuple[str | None, dict[str, Any]]:
    workflow = get_workflow_definition(workflow_key)
    normalized_prompt = prompt.strip()
    if not normalized_prompt:
        raise WorkflowExecutionError("prompt must not be empty")

    source = _resolve_workflow_source(
        session,
        dataset_key=dataset_key,
        rag_collection_id=rag_collection_id,
    )
    if model_id:
        _resolve_workflow_model(session, model_id=model_id)
    payload = {
        "workflow_key": workflow.key,
        "prompt": normalized_prompt,
        "k": max(1, min(int(top_k), 8)),
    }
    if source.dataset_key is not None:
        payload["dataset_key"] = source.dataset_key
    if source.rag_collection_id is not None:
        payload["rag_collection_id"] = source.rag_collection_id
    if model_id:
        payload["model_id"] = model_id
    return source.dataset_key, payload


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    fenced_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
    candidate = fenced_match.group(1) if fenced_match else text

    if not candidate.startswith("{"):
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start >= 0 and end > start:
            candidate = candidate[start : end + 1]

    parsed = json.loads(candidate)
    if not isinstance(parsed, dict):
        raise WorkflowExecutionError("workflow output must be a JSON object")
    return parsed


def _render_schema_hint(workflow_key: str) -> str:
    workflow = get_workflow_definition(workflow_key)
    return workflow.schema_hint


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _extract_string_value(value: Any) -> str | None:
    if isinstance(value, str):
        text = _normalize_text(value)
        return text or None

    if isinstance(value, dict):
        preferred_keys = (
            "action",
            "finding",
            "recommendation",
            "summary",
            "title",
            "text",
            "description",
            "label",
            "name",
        )
        for key in preferred_keys:
            candidate = value.get(key)
            extracted = _extract_string_value(candidate)
            if extracted:
                return extracted

        for candidate in value.values():
            extracted = _extract_string_value(candidate)
            if extracted:
                return extracted

    if isinstance(value, list):
        for candidate in value:
            extracted = _extract_string_value(candidate)
            if extracted:
                return extracted

    return None


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        extracted = _extract_string_value(item)
        if extracted and extracted not in seen:
            normalized.append(extracted)
            seen.add(extracted)
    return normalized


def _build_evidence_fallback_findings(evidence: list[Any]) -> list[str]:
    fallback_findings: list[str] = []
    for item in evidence[:3]:
        snippet = ""
        for raw_line in item.text.splitlines():
            cleaned = re.sub(r"^[#>*`\\-\\d.()\\s]+", "", raw_line).strip()
            if cleaned:
                snippet = cleaned
                break

        text = _normalize_text(f"{item.title}: {snippet or item.text}")
        if text:
            fallback_findings.append(text)

    return fallback_findings


def _normalize_workflow_output(
    workflow_key: str,
    parsed: dict[str, Any],
    *,
    evidence: list[Any],
) -> dict[str, Any]:
    normalized = dict(parsed)

    if workflow_key == "briefing":
        if summary := _extract_string_value(normalized.get("summary")):
            normalized["summary"] = summary
        normalized["key_points"] = _normalize_string_list(normalized.get("key_points"))
        return normalized

    if workflow_key == "recommendation":
        if rationale := _extract_string_value(normalized.get("rationale")):
            normalized["rationale"] = rationale
        normalized["recommendations"] = _normalize_string_list(
            normalized.get("recommendations")
        )
        return normalized

    if title := _extract_string_value(normalized.get("title")):
        normalized["title"] = title
    if executive_summary := _extract_string_value(normalized.get("executive_summary")):
        normalized["executive_summary"] = executive_summary

    findings = _normalize_string_list(normalized.get("findings"))
    normalized["findings"] = findings or _build_evidence_fallback_findings(evidence)
    normalized["actions"] = _normalize_string_list(normalized.get("actions"))
    return normalized


def _build_workflow_prompt(
    *,
    workflow: WorkflowDefinition,
    dataset: ResolvedDataset,
    user_prompt: str,
) -> str:
    profile = get_profile(dataset.profile_key)
    return (
        f"Workflow: {workflow.title}\n"
        f"Dataset: {dataset.title} ({profile.title})\n"
        f"Dataset description: {profile.description}\n"
        f"Analysis focus: {profile.analysis_focus}\n"
        f"User request: {user_prompt}\n\n"
        f"Instructions: {workflow.llm_instruction}\n"
        "Do not fabricate evidence. Do not include markdown fences or explanatory text. "
        f"Return only a JSON object matching this shape: {_render_schema_hint(workflow.key)}"
    )


def _build_collection_workflow_prompt(
    *,
    workflow: WorkflowDefinition,
    source: WorkflowSourceSelection,
    user_prompt: str,
) -> str:
    return (
        f"Workflow: {workflow.title}\n"
        f"Source: {source.source_label} (RAG collection)\n"
        f"Source description: {source.collection_description or 'No collection description provided.'}\n"
        f"User request: {user_prompt}\n\n"
        f"Instructions: {workflow.llm_instruction}\n"
        "Do not fabricate evidence. Do not include markdown fences or explanatory text. "
        f"Return only a JSON object matching this shape: {_render_schema_hint(workflow.key)}"
    )


def execute_workflow(
    *,
    session: Session,
    payload: dict[str, Any],
    llm_client: LLMClient,
    embedding_client: EmbeddingClient,
) -> dict[str, Any]:
    workflow_key = str(payload.get("workflow_key", "")).strip()
    user_prompt = str(payload.get("prompt", "")).strip()
    dataset_key = str(payload.get("dataset_key", "")).strip() or None
    rag_collection_id = str(payload.get("rag_collection_id", "")).strip() or None
    model_id = str(payload.get("model_id", "")).strip() or None

    try:
        top_k = int(payload.get("k", 4))
        workflow = get_workflow_definition(workflow_key)
        source = _resolve_workflow_source(
            session,
            dataset_key=dataset_key,
            rag_collection_id=rag_collection_id,
        )
        selected_model = _resolve_workflow_model(session, model_id=model_id)
    except KeyError as exc:
        raise WorkflowExecutionError(f"workflow not found: {workflow_key}") from exc
    except ValueError as exc:
        raise WorkflowExecutionError(str(exc)) from exc

    if not user_prompt:
        raise WorkflowExecutionError("workflow prompt must not be empty")

    source_meta = _build_source_meta(source)
    model_meta = _build_model_meta(selected_model)

    if source.dataset is not None:
        try:
            evidence = retrieve_evidence(
                dataset=source.dataset,
                query_text=user_prompt,
                top_k=top_k,
                embedding_client=embedding_client,
            )
        except RAGIndexNotReadyError as exc:
            return _rag_index_not_ready_result(
                workflow_key=workflow.key,
                dataset_key=source.dataset.key,
                user_prompt=user_prompt,
                db_path=str(exc.db_path),
                source_meta=source_meta,
                model_meta=model_meta,
            )
        if not evidence:
            raise WorkflowExecutionError("workflow execution produced no evidence")
        question = _build_workflow_prompt(
            workflow=workflow,
            dataset=source.dataset,
            user_prompt=user_prompt,
        )
    else:
        evidence, rag_status = _retrieve_collection_evidence(
            session,
            collection_id=source.collection_id or "",
            query_text=user_prompt,
            top_k=top_k,
        )
        if not evidence:
            return _build_collection_context_unavailable_result(
                workflow_key=workflow.key,
                user_prompt=user_prompt,
                source_meta=source_meta,
                model_meta=model_meta,
                rag_status=rag_status,
            )
        question = _build_collection_workflow_prompt(
            workflow=workflow,
            source=source,
            user_prompt=user_prompt,
        )

    grounding_context = build_grounding_context(evidence)

    try:
        chat_result = llm_client.generate_answer(
            question=question,
            context=grounding_context,
            model=str(selected_model.get("serving_model_name") or "").strip() or None,
            max_tokens=WORKFLOW_MAX_TOKENS,
        )
    except LLMClientError as exc:
        raise WorkflowExecutionError(f"LLM request failed: {exc}") from exc

    try:
        parsed = _extract_json_object(chat_result.answer)
        parsed.pop("evidence", None)
        parsed = _normalize_workflow_output(workflow.key, parsed, evidence=evidence)
        draft_model = DRAFT_MODEL_BY_WORKFLOW_KEY[workflow.key]
        draft = draft_model.model_validate(parsed)
        result_model = RESULT_MODEL_BY_WORKFLOW_KEY[workflow.key]
        final_meta = {
            **source_meta,
            **_build_model_meta(
                selected_model,
                selected_model_name=chat_result.model,
                used_fallback=chat_result.used_fallback,
            ),
            "prompt": user_prompt,
            "warnings": [],
        }
        final_result = result_model.model_validate(
            {
                **draft.model_dump(),
                "evidence": [item.model_dump() for item in evidence],
                "meta": final_meta,
            }
        )
    except (json.JSONDecodeError, ValidationError) as exc:
        raise WorkflowExecutionError(
            f"workflow output validation failed: {exc}"
        ) from exc

    return final_result.model_dump(mode="json")
