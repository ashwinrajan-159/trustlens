"""Schemas for the fraud-ops closed loop (Phase 12)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    FPReasonCode,
    ReportRecommendation,
    ReviewDecision,
    SignalSeverity,
    WeightConfigStatus,
)


# ── Claim / transition ──
class ClaimResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    claimed_by: str | None
    claimed_at: datetime | None


class TransitionRequest(BaseModel):
    target_status: str = Field(min_length=1, max_length=24)
    reason: str = Field(default="", max_length=2000)


# ── Investigation ──
class InvestigationReportCreate(BaseModel):
    investigation_summary: str = Field(min_length=1, max_length=8000)
    findings: str = Field(default="", max_length=8000)
    evidence: dict = Field(default_factory=dict)
    recommendation: ReportRecommendation = ReportRecommendation.REQUEST_INFORMATION


class InvestigationReportPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    alert_id: str
    case_id: str | None
    underwriter_id: str
    investigation_summary: str
    findings: str
    evidence: dict | None
    recommendation: ReportRecommendation
    created_at: datetime


# ── Review ──
class ReviewDecisionCreate(BaseModel):
    decision: ReviewDecision
    comments: str = Field(default="", max_length=8000)
    fp_reason_code: FPReasonCode | None = None


class ReviewDecisionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    report_id: str
    alert_id: str
    reviewer_id: str
    decision: ReviewDecision
    comments: str
    fp_reason_code: FPReasonCode | None
    created_at: datetime


# ── Knowledge base ──
class FraudPatternPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    category: str
    description: str
    severity: SignalSeverity
    detection_logic: dict
    occurrences: int
    confirmed_cases: int
    false_positive_count: int
    pattern_confidence: float
    created_at: datetime


class PatternMergeRequest(BaseModel):
    source_id: str
    target_id: str


# ── Signal analytics ──
class SignalPerformancePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    signal_name: str
    times_triggered: int
    confirmed_fraud_count: int
    false_positive_count: int
    precision_score: float
    sample_sufficient: bool
    precision_ci_low: float
    precision_ci_high: float
    last_updated: datetime | None


# ── Weight governance ──
class WeightProposeRequest(BaseModel):
    weights: dict[str, float] = Field(min_length=1)
    rationale: str = Field(min_length=1, max_length=4000)


class WeightConfigPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    version: int
    weights: dict
    status: WeightConfigStatus
    rationale: str
    created_by: str | None
    approved_by: str | None
    activated_at: datetime | None
    created_at: datetime
