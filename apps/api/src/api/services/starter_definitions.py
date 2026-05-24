from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AppDefinition:
    title: str
    version: str = "0.9.0"


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
        eyebrow="Demo-first reviewer experience",
        subtitle=(
            "Manage RAG collections, build fine-tuning datasets from them, run MLX QLoRA "
            "training, and load the resulting model in LM Studio for inference."
        ),
    ),
)


def get_default_starter() -> StarterDefinition:
    return DEFAULT_STARTER
