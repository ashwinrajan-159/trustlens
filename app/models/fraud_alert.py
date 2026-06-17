"""Fraud alert — an actionable, SLA-tracked escalation for an application (Phase 10).

Created by the real-time engine when a high-severity event fires (or manually). Carries
the RBI reporting requirement + deadline derived from the loan exposure, and an analyst
SLA clock. PII-free (IDs + scalars).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import AlertStatus, AlertType, RBIReportType, SignalSeverity


class FraudAlert(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "fraud_alerts"

    alert_number: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    application_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("applications.id"), index=True, nullable=False
    )
    alert_type: Mapped[AlertType] = mapped_column(
        SAEnum(AlertType, native_enum=False, length=32), nullable=False
    )
    severity: Mapped[SignalSeverity] = mapped_column(
        SAEnum(SignalSeverity, native_enum=False, length=16), index=True, nullable=False
    )
    status: Mapped[AlertStatus] = mapped_column(
        SAEnum(AlertStatus, native_enum=False, length=16),
        default=AlertStatus.OPEN, index=True, nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # RBI Fraud Management reporting.
    rbi_reporting_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rbi_report_type: Mapped[RBIReportType] = mapped_column(
        SAEnum(RBIReportType, native_enum=False, length=16),
        default=RBIReportType.NONE, nullable=False,
    )
    rbi_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_breached: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FraudAlert {self.alert_number} {self.severity.value} {self.status.value}>"
