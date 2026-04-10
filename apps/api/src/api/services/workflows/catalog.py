from __future__ import annotations

from api.services import starter_definitions
from api.services.starter_definitions import WorkflowDefinition


WORKFLOW_KEYS: tuple[str, ...] = tuple(
    item.key for item in starter_definitions.get_default_starter().workflows
)


def list_workflows() -> list[WorkflowDefinition]:
    return list(starter_definitions.get_default_starter().workflows)


def get_workflow_definition(workflow_key: str) -> WorkflowDefinition:
    for workflow in starter_definitions.get_default_starter().workflows:
        if workflow.key == workflow_key:
            return workflow
    raise KeyError(workflow_key)
