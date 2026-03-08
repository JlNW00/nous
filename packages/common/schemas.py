"""Pydantic schemas for API boundaries and internal data transfer."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ── API Request Schemas ─────────────────────────────────────────────────────


class AnalyzeRequest(BaseModel):
    """POST /cases/analyze — §15.1"""

    chain: str
    token_address: str | None = None
    contract_address: str | None = None
    project_name: str | None = None
    wallet_address: str | None = None
    domain: str | None = None
    github_repo: str | None = None
    x_handle: str | None = None

    @field_validator("chain")
    @classmethod
    def validate_chain(cls, v: str) -> str:
        allowed = {"ethereum", "solana", "base", "arbitrum", "polygon", "bsc", "avalanche", "other"}
        if v.lower() not in allowed:
            raise ValueError(f"chain must be one of {allowed}")
        return v.lower()


class ManualLabelRequest(BaseModel):
    """POST /labels/manual"""

    case_id: uuid.UUID
    author: str
    note: str


class ProjectSearchParams(BaseModel):
    """GET /projects/search?q="""

    q: str = Field(min_length=1, max_length=200)


# ── API Response Schemas ────────────────────────────────────────────────────


class CaseCreatedResponse(BaseModel):
    case_id: uuid.UUID
    project_id: uuid.UUID
    status: str


class CaseStatusResponse(BaseModel):
    case_id: uuid.UUID
    project_id: uuid.UUID
    status: str
    priority: str
    created_at: datetime
    updated_at: datetime


class ProjectSummary(BaseModel):
    project_id: uuid.UUID
    canonical_name: str
    symbol: str | None
    chain: str
    primary_contract: str | None
    aliases: list[str] = []


class SignalDetail(BaseModel):
    signal_name: str
    signal_value: float | None
    score_component: str | None
    confidence: float
    evidence_refs: list[uuid.UUID] = []
    calculated_at: datetime


class ReportResponse(BaseModel):
    """GET /reports/{case_id}/latest — §15.2"""

    report_id: uuid.UUID
    case_id: uuid.UUID
    version: int
    generated_at: datetime
    credibility_score: float | None
    verdict: str | None
    confidence: float | None
    report_json: dict[str, Any]
    signals: list[SignalDetail] = []


class TimelineEvent(BaseModel):
    timestamp: datetime
    event_type: str
    description: str
    source: str | None = None
    evidence_id: uuid.UUID | None = None


class EntityProfile(BaseModel):
    entity_id: uuid.UUID
    cluster_label: str | None
    cluster_score: float | None
    linked_wallets: list[str] = []
    linked_projects: list[uuid.UUID] = []


# ── Internal Transfer Objects ───────────────────────────────────────────────


class EvidencePayload(BaseModel):
    """Normalized output from a provider adapter."""

    source_type: str
    provider: str
    payload: dict[str, Any]
    raw_hash: str


class InvestigationPayload(BaseModel):
    """Full payload sent to the reasoning layer — §6.4 output."""

    case_id: uuid.UUID
    project_summary: dict[str, Any]
    signals: list[SignalDetail]
    timeline: list[TimelineEvent]
    entity_graph_summary: dict[str, Any]
    raw_evidence_count: int


class ReasoningOutput(BaseModel):
    """Structured LLM response — §14."""

    summary: str
    supporting_findings: list[str]
    contradictions: list[str]
    open_questions: list[str]
    verdict_suggestion: str
    confidence: float = Field(ge=0.0, le=1.0)
