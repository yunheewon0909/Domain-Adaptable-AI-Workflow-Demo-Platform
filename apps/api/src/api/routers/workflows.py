from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from api.db import get_engine
from api.services.jobs import create_job
from api.services.workflows.catalog import get_workflow_definition, list_workflows
from api.services.workflows.service import WorkflowExecutionError, create_workflow_job_payload

router = APIRouter(tags=["workflows"])


class WorkflowJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1)
    dataset_key: str | None = None
    k: int = Field(default=4, ge=1, le=8)


@router.get("/workflows")
def get_workflows() -> list[dict[str, object]]:
    return [
        {
            "key": workflow.key,
            "title": workflow.title,
            "summary": workflow.summary,
            "prompt_label": workflow.prompt_label,
            "output_fields": workflow.output_fields,
        }
        for workflow in list_workflows()
    ]


@router.post("/workflows/{workflow_key}/jobs", status_code=202)
def enqueue_workflow_job(workflow_key: str, request: WorkflowJobRequest) -> dict[str, Any]:
    try:
        get_workflow_definition(workflow_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="workflow not found") from exc

    with Session(get_engine()) as session:
        try:
            dataset, payload = create_workflow_job_payload(
                session,
                workflow_key=workflow_key,
                prompt=request.prompt,
                dataset_key=request.dataset_key,
                top_k=request.k,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="workflow not found") from exc
        except WorkflowExecutionError as exc:
            message = str(exc)
            status_code = 404 if "dataset" in message.lower() else 400
            raise HTTPException(status_code=status_code, detail=message) from exc

        job = create_job(
            session,
            job_type="workflow_run",
            payload_json=payload,
            workflow_key=workflow_key,
            dataset_key=dataset.key,
        )
    return {"job_id": job.id, "status": job.status, "workflow_key": workflow_key, "dataset_key": dataset.key}
