"""Investigation case — groups applications/alerts for analyst workflow (Phase 10)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import CasePriority, CaseStatus, CaseType


class InvestigationCase(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "investigation_cases"

    case_number: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    case_type: Mapped[CaseType] = mapped_column(
        SAEnum(CaseType, native_enum=False, length=24), nullable=False
    )
    status: Mapped[CaseStatus] = mapped_column(
        SAEnum(CaseStatus, native_enum=False, length=16),
        default=CaseStatus.OPEN, index=True, nullable=False,
    )
    priority: Mapped[CasePriority] = mapped_column(
        SAEnum(CasePriority, native_enum=False, length=16),
        default=CasePriority.MEDIUM, nullable=False,
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)

    application_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    alert_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)

    assigned_to: Mapped[str | None] = mapped_column(String(36), nullable=True)
    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    closed_outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<InvestigationCase {self.case_number} {self.status.value}>"
