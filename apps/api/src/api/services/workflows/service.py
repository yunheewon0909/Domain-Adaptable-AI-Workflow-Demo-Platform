from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from api.llm import LLMClient, LLMClientError
from api.services.datasets.resolver import (
    DatasetNotFoundError,
    ResolvedDataset,
    resolve_dataset,
)
from api.services.rag.embedding_client import EmbeddingClient
from api.services.retrieval.service import build_grounding_context, retrieve_evidence
from api.services.workflows.catalog import WorkflowDefinition, get_workflow_definition
from api.services.workflows.contracts import (
    DRAFT_MODEL_BY_WORKFLOW_KEY,
    RESULT_MODEL_BY_WORKFLOW_KEY,
)
from api.services.workflows.profiles import get_profile


WORKFLOW_MAX_TOKENS = 512


class WorkflowExecutionError(RuntimeError):
    pass


def create_workflow_job_payload(
    session: Session,
    *,
    workflow_key: str,
    prompt: str,
    dataset_key: str | None,
    top_k: int,
) -> tuple[ResolvedDataset, dict[str, Any]]:
    workflow = get_workflow_definition(workflow_key)
    normalized_prompt = prompt.strip()
    if not normalized_prompt:
        raise WorkflowExecutionError("prompt must not be empty")

    dataset = resolve_dataset(session, dataset_key)
    payload = {
        "workflow_key": workflow.key,
        "dataset_key": dataset.key,
        "prompt": normalized_prompt,
        "k": max(1, min(int(top_k), 8)),
    }
    return dataset, payload


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

    try:
        top_k = int(payload.get("k", 4))
        workflow = get_workflow_definition(workflow_key)
        dataset = resolve_dataset(session, dataset_key)
    except DatasetNotFoundError as exc:
        raise WorkflowExecutionError(
            f"dataset not found: {dataset_key or 'active'}"
        ) from exc
    except KeyError as exc:
        raise WorkflowExecutionError(f"workflow not found: {workflow_key}") from exc
    except ValueError as exc:
        raise WorkflowExecutionError(str(exc)) from exc

    if not user_prompt:
        raise WorkflowExecutionError("workflow prompt must not be empty")

    evidence = retrieve_evidence(
        dataset=dataset,
        query_text=user_prompt,
        top_k=top_k,
        embedding_client=embedding_client,
    )
    if not evidence:
        raise WorkflowExecutionError("workflow execution produced no evidence")

    grounding_context = build_grounding_context(evidence)
    question = _build_workflow_prompt(
        workflow=workflow,
        dataset=dataset,
        user_prompt=user_prompt,
    )

    try:
        chat_result = llm_client.generate_answer(
            question=question,
            context=grounding_context,
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
        final_result = result_model.model_validate(
            {
                **draft.model_dump(),
                "evidence": [item.model_dump() for item in evidence],
            }
        )
    except (json.JSONDecodeError, ValidationError) as exc:
        raise WorkflowExecutionError(
            f"workflow output validation failed: {exc}"
        ) from exc

    return final_result.model_dump(mode="json")
