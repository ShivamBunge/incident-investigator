"""Pydantic v2 models at API boundaries."""

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field, model_validator

DocumentType = Literal["runbook", "postmortem", "known_issue"]

SourceType = Literal["observability", "kubernetes", "rag_document", "derived"]

EvidenceType = Literal[
    "metric",
    "deployment",
    "log_signature",
    "workload_status",
    "pod_status",
    "runbook_chunk",
    "postmortem_chunk",
    "derived_statistic",
]

MAX_WINDOW_HOURS = 6.0


# --- Documents --------------------------------------------------------------


class DocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    document_type: DocumentType
    service: str | None = Field(default=None, max_length=255)
    content: str = Field(min_length=1)
    source_uri: str | None = Field(default=None, max_length=1024)


class DocumentCreated(BaseModel):
    id: str
    title: str
    document_type: DocumentType
    service: str | None
    chunk_count: int
    created: bool


class DocumentSummary(BaseModel):
    id: str
    title: str
    document_type: DocumentType
    service: str | None
    created_at: datetime


# --- Investigations ---------------------------------------------------------


class TimeRange(BaseModel):
    start: datetime
    end: datetime


class InvestigationCreate(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    service: str = Field(min_length=1, max_length=255)
    time_range: TimeRange

    @model_validator(mode="after")
    def _validate_window(self) -> "InvestigationCreate":
        if self.time_range.start >= self.time_range.end:
            raise ValueError("time_range.start must be before time_range.end")
        if (self.time_range.end - self.time_range.start) > timedelta(hours=MAX_WINDOW_HOURS):
            raise ValueError(f"time window exceeds {MAX_WINDOW_HOURS} hours")
        return self


class Finding(BaseModel):
    statement: str
    evidence_ids: list[str] = Field(default_factory=list)


class Hypothesis(BaseModel):
    statement: str
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)


class Recommendation(BaseModel):
    statement: str
    reason: str


class SynthesisResult(BaseModel):
    """LLM output contract (spec Section 9)."""

    summary: str
    findings: list[Finding] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)


class EvidenceOut(BaseModel):
    id: str
    source_type: str
    evidence_type: str
    observed_at: datetime | None = None
    summary: str
    source_locator: dict = Field(default_factory=dict)


class TimelineEventOut(BaseModel):
    timestamp: datetime
    kind: str
    description: str
    evidence_id: str


class InvestigationResult(BaseModel):
    investigation_id: str
    question: str
    service: str
    status: str
    summary: str
    findings: list[Finding] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    timeline: list[TimelineEventOut] = Field(default_factory=list)
    evidence: list[EvidenceOut] = Field(default_factory=list)
    unavailable_sources: list[str] = Field(default_factory=list)
    rejected_evidence_ids: list[str] = Field(default_factory=list)