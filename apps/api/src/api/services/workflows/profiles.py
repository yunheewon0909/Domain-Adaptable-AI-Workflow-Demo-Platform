from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowProfile:
    key: str
    title: str
    description: str
    analysis_focus: str


_PROFILE_BY_KEY = {
    "industrial_ops": WorkflowProfile(
        key="industrial_ops",
        title="Industrial Operations",
        description="Operational maintenance, uptime, and plant process documentation.",
        analysis_focus="Prioritize operational risks, maintenance insights, and practical actions.",
    ),
    "enterprise_docs": WorkflowProfile(
        key="enterprise_docs",
        title="Enterprise Knowledge",
        description="General business, enablement, and internal knowledge artifacts.",
        analysis_focus="Prioritize stakeholder clarity, decision support, and execution readiness.",
    ),
}


def get_profile(profile_key: str) -> WorkflowProfile:
    return _PROFILE_BY_KEY.get(
        profile_key,
        WorkflowProfile(
            key=profile_key,
            title=profile_key.replace("_", " ").title(),
            description="General-purpose knowledge corpus.",
            analysis_focus="Stay grounded in evidence and keep the response concise and actionable.",
        ),
    )
