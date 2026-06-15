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


class PropertyProfilePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    application_id: str
    survey_numbers: list | None
    area: float | None
    sale_consideration: float | None
    valuation: float | None
    valuation_ratio: float | None
    is_inflated: bool
    duplicate_collateral_app_ids: list | None
    created_at: datetime


class BusinessProfilePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    application_id: str
    itr_revenue: float | None
    gst_revenue: float | None
    net_profit: float | None
    revenue_gap_ratio: float | None
    created_at: datetime


class GraphAnalysisPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    application_id: str
    graph_risk_score: float
    fraud_connections_count: int
    shared_pan_count: int
    shared_account_count: int
    shared_property_count: int
    ring_size: int
    in_fraud_ring: bool
    connected_application_ids: list | None
    created_at: datetime


class NetworkNode(BaseModel):
    id: str
    kind: str
    label: str


class NetworkEdge(BaseModel):
    source: str
    target: str


class NetworkResponse(BaseModel):
    nodes: list[NetworkNode]
    edges: list[NetworkEdge]


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
