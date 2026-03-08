from __future__ import annotations

from dataclasses import dataclass

from api.services.workflows.contracts import WorkflowKey


@dataclass(frozen=True)
class WorkflowDefinition:
    key: WorkflowKey
    title: str
    summary: str
    prompt_label: str
    output_fields: list[str]
    llm_instruction: str


_WORKFLOW_CATALOG: tuple[WorkflowDefinition, ...] = (
    WorkflowDefinition(
        key="briefing",
        title="Briefing",
        summary="Create a concise evidence-backed briefing for a selected dataset.",
        prompt_label="What should this briefing focus on?",
        output_fields=["summary", "key_points", "evidence"],
        llm_instruction=(
            "Produce an executive-ready briefing. Focus on the user's goal, synthesize the most relevant evidence, "
            "and return strict JSON with only `summary` and `key_points` fields."
        ),
    ),
    WorkflowDefinition(
        key="recommendation",
        title="Recommendation",
        summary="Generate evidence-backed recommendations and a concise rationale.",
        prompt_label="What decision or recommendation is needed?",
        output_fields=["recommendations", "rationale", "evidence"],
        llm_instruction=(
            "Produce decision-oriented recommendations grounded in the retrieved evidence. "
            "Return strict JSON with only `recommendations` and `rationale` fields."
        ),
    ),
    WorkflowDefinition(
        key="report_generator",
        title="Report Generator",
        summary="Assemble a lightweight report with findings, actions, and supporting evidence.",
        prompt_label="What report should be generated?",
        output_fields=["title", "executive_summary", "findings", "actions", "evidence"],
        llm_instruction=(
            "Produce a compact structured report for the user's request. "
            "Return strict JSON with only `title`, `executive_summary`, `findings`, and `actions` fields."
        ),
    ),
)

WORKFLOW_KEYS: tuple[str, ...] = tuple(item.key for item in _WORKFLOW_CATALOG)
_WORKFLOW_BY_KEY = {item.key: item for item in _WORKFLOW_CATALOG}


def list_workflows() -> list[WorkflowDefinition]:
    return list(_WORKFLOW_CATALOG)


def get_workflow_definition(workflow_key: str) -> WorkflowDefinition:
    workflow = _WORKFLOW_BY_KEY.get(workflow_key)
    if workflow is None:
        raise KeyError(workflow_key)
    return workflow
