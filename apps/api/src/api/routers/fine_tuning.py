from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from api.db import get_engine
from api.dependencies import get_llm_client
from api.llm import LLMClient
from api.services.fine_tuning import (
    add_dataset_rows,
    create_dataset,
    create_dataset_version,
    create_qa_pair,
    delete_dataset_row,
    get_dataset,
    get_dataset_version,
    get_qa_pairs,
    list_dataset_rows,
    list_datasets,
    set_dataset_version_status,
    update_dataset_row,
)
from api.services.fine_tuning.qa_generator import (
    build_dataset_rows,
    generate_pairs_from_collection,
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


class CreateQAPairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(default="")
    answer: str = Field(default="")


class UpdateQAPairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)


class CreateFTDatasetFromRAGRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rag_collection_id: str = Field(min_length=1)
    dataset_name: str = Field(min_length=1)
    version_label: str = Field(default="v1", min_length=1)
    description: str | None = None
    max_chunks: int = Field(default=50, ge=1, le=500)
    pairs_per_chunk: int = Field(default=3, ge=1, le=20)
    chunk_chars: int = Field(default=1500, ge=200, le=8000)
    chat_model: str | None = None


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


@router.post("/ft-datasets/from-rag-collection", status_code=201)
def post_ft_dataset_from_rag(
    request: CreateFTDatasetFromRAGRequest,
    llm_client: LLMClient = Depends(get_llm_client),
) -> dict[str, Any]:
    """Build an instruction_sft dataset by asking the LLM to generate Q/A pairs
    grounded in a RAG collection's documents.

    The endpoint creates the dataset + a draft version + train-split rows in
    one shot. The reviewer then validates and locks the version through the
    existing `/ft-dataset-versions/{id}/status` flow before enqueueing
    training.
    """
    with Session(get_engine()) as session:
        try:
            generation = generate_pairs_from_collection(
                session,
                collection_id=request.rag_collection_id,
                llm_client=llm_client,
                max_chunks=request.max_chunks,
                pairs_per_chunk=request.pairs_per_chunk,
                chunk_chars=request.chunk_chars,
                chat_model=request.chat_model,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="RAG collection not found"
            ) from exc

        if not generation.pairs:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "No Q/A pairs were generated from the collection.",
                    "chunk_count": generation.chunk_count,
                    "errors": [
                        {
                            "document_id": err.document_id,
                            "chunk_index": err.chunk_index,
                            "reason": err.reason,
                        }
                        for err in generation.errors
                    ],
                },
            )

        try:
            dataset = create_dataset(
                session,
                name=request.dataset_name,
                task_type="instruction_sft",
                schema_type="json",
                description=request.description
                or f"Generated from RAG collection {request.rag_collection_id}.",
            )
            version = create_dataset_version(
                session,
                dataset_id=dataset["id"],
                version_label=request.version_label,
                train_split_ratio=1.0,
                val_split_ratio=0.0,
                test_split_ratio=0.0,
            )
            rows = build_dataset_rows(
                generation.pairs, collection_id=request.rag_collection_id
            )
            add_result = add_dataset_rows(
                session, version_id=version["id"], rows=rows
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "dataset_id": dataset["id"],
            "dataset_version_id": version["id"],
            "row_count": len(rows),
            "chunk_count": generation.chunk_count,
            "rejected_chunk_count": len(generation.errors),
            "errors": [
                {
                    "document_id": err.document_id,
                    "chunk_index": err.chunk_index,
                    "reason": err.reason,
                }
                for err in generation.errors
            ],
            "version_status": add_result.get("status", version.get("status")),
        }


@router.post("/ft-dataset-versions/{version_id}/qa-pairs", status_code=201)
def post_ft_qa_pair(version_id: str, request: CreateQAPairRequest) -> dict[str, Any]:
    """Add a new Q/A pair to a dataset version."""
    with Session(get_engine()) as session:
        try:
            return create_qa_pair(
                session,
                version_id=version_id,
                question=request.question,
                answer=request.answer,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/ft-dataset-versions/{version_id}/qa-pairs")
def get_ft_qa_pairs(version_id: str) -> list[dict[str, Any]]:
    """Return Q/A pairs in a user-readable format for frontend review and editing."""
    with Session(get_engine()) as session:
        if get_dataset_version(session, version_id) is None:
            raise HTTPException(
                status_code=404, detail="fine-tuning dataset version not found"
            )
        return get_qa_pairs(session, version_id)


@router.put("/ft-dataset-versions/{version_id}/qa-pairs/{row_id}")
def put_ft_qa_pair(
    version_id: str, row_id: int, request: UpdateQAPairRequest
) -> dict[str, Any]:
    """Update a single Q/A pair's question and answer."""
    with Session(get_engine()) as session:
        try:
            return update_dataset_row(
                session,
                version_id=version_id,
                row_id=row_id,
                question=request.question,
                answer=request.answer,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/ft-dataset-versions/{version_id}/qa-pairs/{row_id}", status_code=204)
def delete_ft_qa_pair(version_id: str, row_id: int) -> None:
    """Delete a single Q/A pair from a dataset version."""
    with Session(get_engine()) as session:
        try:
            delete_dataset_row(session, version_id=version_id, row_id=row_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
