from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias


WorkflowKey: TypeAlias = Literal["briefing", "recommendation", "report_generator"]


@dataclass(frozen=True)
class AppDefinition:
    title: str
    version: str = "0.6.0"


@dataclass(frozen=True)
class DemoDefinition:
    enabled: bool
    eyebrow: str
    subtitle: str


@dataclass(frozen=True)
class DatasetDefinition:
    key: str
    title: str
    domain_type: str
    profile_key: str
    source_dir: str
    index_dir: str
    db_path: str
    is_active: bool = False


@dataclass(frozen=True)
class WorkflowProfileDefinition:
    key: str
    title: str
    description: str
    analysis_focus: str


@dataclass(frozen=True)
class WorkflowDefinition:
    key: WorkflowKey
    title: str
    summary: str
    prompt_label: str
    output_fields: tuple[str, ...]
    llm_instruction: str
    schema_hint: str


@dataclass(frozen=True)
class StarterDefinition:
    app: AppDefinition
    demo: DemoDefinition
    datasets: tuple[DatasetDefinition, ...]
    workflows: tuple[WorkflowDefinition, ...]
    profiles: tuple[WorkflowProfileDefinition, ...]


DEFAULT_STARTER = StarterDefinition(
    app=AppDefinition(title="Domain-Adaptable AI Workflow Demo API"),
    demo=DemoDefinition(
        enabled=True,
        eyebrow="Demo-first reviewer experience",
        subtitle=(
            "Switch between retrieval-first reviewer workflows and a PLC testing MVP that imports suites, queues deterministic runs, and exposes testcase-level results."
        ),
    ),
    datasets=(
        DatasetDefinition(
            key="industrial_demo",
            title="Industrial Operations Demo",
            domain_type="industrial_ops",
            profile_key="industrial_ops",
            source_dir="data/sample_docs",
            index_dir="data/rag_index",
            db_path="data/rag_index/rag.db",
            is_active=True,
        ),
        DatasetDefinition(
            key="enterprise_docs",
            title="Enterprise Knowledge Demo",
            domain_type="enterprise_docs",
            profile_key="enterprise_docs",
            source_dir="data/datasets/enterprise_docs/source",
            index_dir="data/datasets/enterprise_docs/index",
            db_path="data/datasets/enterprise_docs/index/rag.db",
            is_active=False,
        ),
    ),
    workflows=(
        WorkflowDefinition(
            key="briefing",
            title="Briefing",
            summary="Create a concise evidence-backed briefing for a selected dataset.",
            prompt_label="What should this briefing focus on?",
            output_fields=("summary", "key_points", "evidence"),
            llm_instruction=(
                "Produce an executive-ready briefing. Focus on the user's goal, synthesize the most relevant evidence, "
                "and return strict JSON with only `summary` and `key_points` fields."
            ),
            schema_hint='{"summary":"...","key_points":["..."]}',
        ),
        WorkflowDefinition(
            key="recommendation",
            title="Recommendation",
            summary="Generate evidence-backed recommendations and a concise rationale.",
            prompt_label="What decision or recommendation is needed?",
            output_fields=("recommendations", "rationale", "evidence"),
            llm_instruction=(
                "Produce decision-oriented recommendations grounded in the retrieved evidence. "
                "Return strict JSON with only `recommendations` and `rationale` fields."
            ),
            schema_hint='{"recommendations":["..."],"rationale":"..."}',
        ),
        WorkflowDefinition(
            key="report_generator",
            title="Report Generator",
            summary="Assemble a lightweight report with findings, actions, and supporting evidence.",
            prompt_label="What report should be generated?",
            output_fields=(
                "title",
                "executive_summary",
                "findings",
                "actions",
                "evidence",
            ),
            llm_instruction=(
                "Produce a compact structured report for the user's request. "
                "Return strict JSON with only `title`, `executive_summary`, `findings`, and `actions` fields."
            ),
            schema_hint='{"title":"...","executive_summary":"...","findings":["..."],"actions":["..."]}',
        ),
    ),
    profiles=(
        WorkflowProfileDefinition(
            key="industrial_ops",
            title="Industrial Operations",
            description="Operational maintenance, uptime, and plant process documentation.",
            analysis_focus="Prioritize operational risks, maintenance insights, and practical actions.",
        ),
        WorkflowProfileDefinition(
            key="enterprise_docs",
            title="Enterprise Knowledge",
            description="General business, enablement, and internal knowledge artifacts.",
            analysis_focus="Prioritize stakeholder clarity, decision support, and execution readiness.",
        ),
    ),
)


def get_default_starter() -> StarterDefinition:
    return DEFAULT_STARTER


def get_primary_dataset_definition(
    starter: StarterDefinition | None = None,
) -> DatasetDefinition:
    active_starter = starter or get_default_starter()
    for dataset in active_starter.datasets:
        if dataset.is_active:
            return dataset
    return active_starter.datasets[0]
