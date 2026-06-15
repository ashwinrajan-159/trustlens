"""Fraud-signal + risk-assessment response schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import (
    FraudSignalType,
    LoanType,
    RiskTier,
    SignalScope,
    SignalSeverity,
)


class FraudSignalPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    application_id: str
    document_id: str | None
    signal_type: FraudSignalType
    severity: SignalSeverity
    signal_scope: SignalScope
    description: str
    evidence: dict | None
    confidence: float
    rule_name: str
    engine_version: str
    is_confirmed: bool
    created_at: datetime


class RiskAssessmentPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    application_id: str
    total_score: float
    risk_tier: RiskTier
    reasons: list | None
    by_category: dict | None
    engine_version: str
    created_at: datetime


class CompletenessResponse(BaseModel):
    loan_type: LoanType
    present: list[str]
    missing_critical: list[str]
    missing_recommended: list[str]
    is_complete: bool


class IdentityProfilePublic(BaseModel):
    """Resolved identity for display — only masked PII is exposed."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    application_id: str
    resolved_name_masked: str | None
    pan_masked: str | None
    aadhaar_masked: str | None
    distinct_name_count: int
    distinct_pan_count: int
    distinct_dob_count: int
    synthetic_score: float
    is_synthetic_suspected: bool
    indicators: list | None
    created_at: datetime
