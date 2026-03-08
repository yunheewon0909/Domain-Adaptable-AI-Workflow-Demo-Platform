from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field


WorkflowKey: TypeAlias = Literal["briefing", "recommendation", "report_generator"]


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)
    score: float


class BriefingDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    key_points: list[str] = Field(min_length=1)


class BriefingResult(BriefingDraft):
    evidence: list[EvidenceItem] = Field(min_length=1)


class RecommendationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendations: list[str] = Field(min_length=1)
    rationale: str = Field(min_length=1)


class RecommendationResult(RecommendationDraft):
    evidence: list[EvidenceItem] = Field(min_length=1)


class ReportGeneratorDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    executive_summary: str = Field(min_length=1)
    findings: list[str] = Field(min_length=1)
    actions: list[str] = Field(min_length=1)


class ReportGeneratorResult(ReportGeneratorDraft):
    evidence: list[EvidenceItem] = Field(min_length=1)


WorkflowDraftModel: TypeAlias = type[BriefingDraft] | type[RecommendationDraft] | type[ReportGeneratorDraft]
WorkflowResultModel: TypeAlias = type[BriefingResult] | type[RecommendationResult] | type[ReportGeneratorResult]

DRAFT_MODEL_BY_WORKFLOW_KEY: dict[str, WorkflowDraftModel] = {
    "briefing": BriefingDraft,
    "recommendation": RecommendationDraft,
    "report_generator": ReportGeneratorDraft,
}

RESULT_MODEL_BY_WORKFLOW_KEY: dict[str, WorkflowResultModel] = {
    "briefing": BriefingResult,
    "recommendation": RecommendationResult,
    "report_generator": ReportGeneratorResult,
}
