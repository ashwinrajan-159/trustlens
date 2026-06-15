"""Application schemas."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ApplicationStatus, LoanType, RiskTier


class ApplicationCreate(BaseModel):
    loan_type: LoanType
    loan_amount_requested: Decimal = Field(gt=0, le=Decimal("1000000000"))


class ApplicationDecision(BaseModel):
    approve: bool
    reason: str = Field(min_length=1, max_length=2000)


class ApplicationPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    application_number: str
    applicant_id: str
    loan_type: LoanType
    loan_amount_requested: Decimal
    status: ApplicationStatus
    risk_tier: RiskTier | None
    current_risk_score: float | None
    submitted_at: datetime | None
    created_at: datetime
    updated_at: datetime
