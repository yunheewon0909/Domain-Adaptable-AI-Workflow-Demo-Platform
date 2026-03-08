from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from api.db import get_engine
from api.services.datasets.registry import dataset_to_dict, list_dataset_records, set_active_dataset

router = APIRouter(tags=["datasets"])


class SetActiveDatasetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_key: str = Field(min_length=1)


@router.get("/datasets")
def list_datasets() -> list[dict[str, object]]:
    with Session(get_engine()) as session:
        records = list_dataset_records(session)
    return [dataset_to_dict(record) for record in records]


@router.post("/datasets/active")
def update_active_dataset(request: SetActiveDatasetRequest) -> dict[str, object]:
    with Session(get_engine()) as session:
        try:
            record = set_active_dataset(session, request.dataset_key)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="dataset not found") from exc
    return dataset_to_dict(record)
