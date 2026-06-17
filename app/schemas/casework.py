"""Schemas for alerts, cases, operations and RBI compliance (Phase 10)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    AlertStatus,
    AlertType,
    CasePriority,
    CaseStatus,
    CaseType,
    RBIReportType,
    SignalSeverity,
)


class AlertPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    alert_number: str
    application_id: str
    alert_type: AlertType
    severity: SignalSeverity
    status: AlertStatus
    description: str
    rbi_reporting_required: bool
    rbi_report_type: RBIReportType
    rbi_deadline: datetime | None
    sla_deadline: datetime | None
    sla_breached: bool
    created_at: datetime


class ResolveAlertRequest(BaseModel):
    dismiss: bool = False


class CaseCreate(BaseModel):
    case_type: CaseType = CaseType.INVESTIGATION
    summary: str = Field(min_length=1, max_length=2000)
    priority: CasePriority = CasePriority.MEDIUM
    application_ids: list[str] = []
    alert_ids: list[str] = []


class CaseCloseRequest(BaseModel):
    outcome: str = Field(min_length=1, max_length=64)


class CaseAssignRequest(BaseModel):
    assignee: str


class CasePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_number: str
    case_type: CaseType
    status: CaseStatus
    priority: CasePriority
    summary: str
    application_ids: list | None
    alert_ids: list | None
    assigned_to: str | None
    closed_outcome: str | None
    created_at: datetime


class OperationsOverview(BaseModel):
    applications_total: int
    applications_by_tier: dict[str, int]
    alerts_open: int
    alerts_rbi_reportable: int
    alerts_sla_breached: int
    cases_open: int


class FMRReportResponse(BaseModel):
    report: dict
