from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from api.llm import LLMClient, LLMClientError
from api.services.datasets.resolver import DatasetNotFoundError, ResolvedDataset, resolve_dataset
from api.services.rag.embedding_client import EmbeddingClient
from api.services.retrieval.service import build_grounding_context, retrieve_evidence
from api.services.workflows.catalog import WorkflowDefinition, get_workflow_definition
from api.services.workflows.contracts import (
    DRAFT_MODEL_BY_WORKFLOW_KEY,
    RESULT_MODEL_BY_WORKFLOW_KEY,
)
from api.services.workflows.profiles import get_profile


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
    if workflow_key == "briefing":
        return '{"summary":"...","key_points":["..."]}'
    if workflow_key == "recommendation":
        return '{"recommendations":["..."],"rationale":"..."}'
    return '{"title":"...","executive_summary":"...","findings":["..."],"actions":["..."]}'


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
    try:
        workflow_key = str(payload.get("workflow_key", "")).strip()
        user_prompt = str(payload.get("prompt", "")).strip()
        dataset_key = str(payload.get("dataset_key", "")).strip() or None
        top_k = int(payload.get("k", 4))
        workflow = get_workflow_definition(workflow_key)
        dataset = resolve_dataset(session, dataset_key)
    except KeyError as exc:
        raise WorkflowExecutionError(f"workflow not found: {workflow_key}") from exc
    except DatasetNotFoundError as exc:
        raise WorkflowExecutionError(f"dataset not found: {dataset_key or 'active'}") from exc
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
        chat_result = llm_client.generate_answer(question=question, context=grounding_context)
    except LLMClientError as exc:
        raise WorkflowExecutionError(f"LLM request failed: {exc}") from exc

    try:
        parsed = _extract_json_object(chat_result.answer)
        parsed.pop("evidence", None)
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
        raise WorkflowExecutionError(f"workflow output validation failed: {exc}") from exc

    return final_result.model_dump(mode="json")
