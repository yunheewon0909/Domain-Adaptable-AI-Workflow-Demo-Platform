from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AppDefinition:
    title: str
    version: str = "0.10.0"


@dataclass(frozen=True)
class DemoDefinition:
    enabled: bool
    eyebrow: str
    subtitle: str


@dataclass(frozen=True)
class StarterDefinition:
    app: AppDefinition
    demo: DemoDefinition


DEFAULT_STARTER = StarterDefinition(
    app=AppDefinition(title="Domain-Adaptable AI Workflow Demo API"),
    demo=DemoDefinition(
        enabled=True,
        eyebrow="Admin / evaluation / debug dashboard",
        subtitle=(
            "Inspect RAG collections, trigger Graph RAG indexing, and review "
            "evaluation reports. Chat happens in Open WebUI, not here."
        ),
    ),
)


def get_default_starter() -> StarterDefinition:
    return DEFAULT_STARTER
