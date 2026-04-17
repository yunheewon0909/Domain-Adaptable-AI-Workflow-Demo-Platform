from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from api.db import get_engine
from api.services.fine_tuning import (
    add_dataset_rows,
    create_dataset,
    create_dataset_version,
    get_dataset,
    get_dataset_version,
    list_dataset_rows,
    list_datasets,
    set_dataset_version_status,
)

router = APIRouter(tags=["fine-tuning"])


class CreateFTDatasetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    task_type: str = Field(min_length=1)
    schema_type: str = Field(default="json", min_length=1)
    description: str | None = None


class CreateFTDatasetVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_label: str = Field(min_length=1)
    train_split_ratio: float = Field(default=0.8, ge=0, le=1)
    val_split_ratio: float = Field(default=0.1, ge=0, le=1)
    test_split_ratio: float = Field(default=0.1, ge=0, le=1)


class FTRowPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    split: str = Field(default="unlabeled")
    input_json: dict[str, Any] | list[Any] | str | None = None
    target_json: dict[str, Any] | list[Any] | str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class AddFTRowsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[FTRowPayload]


class UpdateFTDatasetVersionStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(pattern="^(draft|validated|locked)$")


@router.post("/ft-datasets", status_code=201)
def post_ft_dataset(request: CreateFTDatasetRequest) -> dict[str, Any]:
    with Session(get_engine()) as session:
        try:
            return create_dataset(
                session,
                name=request.name,
                task_type=request.task_type,
                schema_type=request.schema_type,
                description=request.description,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/ft-datasets")
def get_ft_datasets() -> list[dict[str, Any]]:
    with Session(get_engine()) as session:
        return list_datasets(session)


@router.get("/ft-datasets/{dataset_id}")
def get_ft_dataset(dataset_id: str) -> dict[str, Any]:
    with Session(get_engine()) as session:
        dataset = get_dataset(session, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="fine-tuning dataset not found")
    return dataset


@router.post("/ft-datasets/{dataset_id}/versions", status_code=201)
def post_ft_dataset_version(
    dataset_id: str, request: CreateFTDatasetVersionRequest
) -> dict[str, Any]:
    with Session(get_engine()) as session:
        try:
            return create_dataset_version(
                session,
                dataset_id=dataset_id,
                version_label=request.version_label,
                train_split_ratio=request.train_split_ratio,
                val_split_ratio=request.val_split_ratio,
                test_split_ratio=request.test_split_ratio,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="fine-tuning dataset not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/ft-dataset-versions/{version_id}")
def get_ft_dataset_version(version_id: str) -> dict[str, Any]:
    with Session(get_engine()) as session:
        version = get_dataset_version(session, version_id)
    if version is None:
        raise HTTPException(
            status_code=404, detail="fine-tuning dataset version not found"
        )
    return version


@router.get("/ft-dataset-versions/{version_id}/summary")
def get_ft_dataset_version_summary(version_id: str) -> dict[str, Any]:
    with Session(get_engine()) as session:
        version = get_dataset_version(session, version_id)
    if version is None:
        raise HTTPException(
            status_code=404, detail="fine-tuning dataset version not found"
        )
    return {key: value for key, value in version.items() if key != "rows"}


@router.post("/ft-dataset-versions/{version_id}/rows", status_code=201)
def post_ft_dataset_rows(version_id: str, request: AddFTRowsRequest) -> dict[str, Any]:
    with Session(get_engine()) as session:
        try:
            return add_dataset_rows(
                session,
                version_id=version_id,
                rows=[item.model_dump(mode="json") for item in request.rows],
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="fine-tuning dataset version not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/ft-dataset-versions/{version_id}/rows")
def get_ft_dataset_rows(version_id: str) -> list[dict[str, Any]]:
    with Session(get_engine()) as session:
        version = get_dataset_version(session, version_id)
        if version is None:
            raise HTTPException(
                status_code=404, detail="fine-tuning dataset version not found"
            )
        return list_dataset_rows(session, version_id)


@router.post("/ft-dataset-versions/{version_id}/status")
def post_ft_dataset_version_status(
    version_id: str, request: UpdateFTDatasetVersionStatusRequest
) -> dict[str, Any]:
    with Session(get_engine()) as session:
        try:
            return set_dataset_version_status(
                session, version_id=version_id, status=request.status
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="fine-tuning dataset version not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
