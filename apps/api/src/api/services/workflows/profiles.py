from __future__ import annotations

from dataclasses import dataclass

from api.services import starter_definitions


@dataclass(frozen=True)
class WorkflowProfile:
    key: str
    title: str
    description: str
    analysis_focus: str


def get_profile(profile_key: str) -> WorkflowProfile:
    for profile in starter_definitions.get_default_starter().profiles:
        if profile.key == profile_key:
            return WorkflowProfile(
                key=profile.key,
                title=profile.title,
                description=profile.description,
                analysis_focus=profile.analysis_focus,
            )
    return WorkflowProfile(
        key=profile_key,
        title=profile_key.replace("_", " ").title(),
        description="General-purpose knowledge corpus.",
        analysis_focus="Stay grounded in evidence and keep the response concise and actionable.",
    )
