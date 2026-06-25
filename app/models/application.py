"""Loan application — the central case entity. All intelligence anchors here."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Numeric,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import ApplicationStatus, LoanType, RiskTier


class Application(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "applications"

    application_number: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, nullable=False
    )
    applicant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), index=True, nullable=False
    )

    loan_type: Mapped[LoanType] = mapped_column(
        SAEnum(LoanType, native_enum=False, length=16), nullable=False
    )
    loan_amount_requested: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)

    status: Mapped[ApplicationStatus] = mapped_column(
        SAEnum(ApplicationStatus, native_enum=False, length=24),
        default=ApplicationStatus.DRAFT,
        index=True,
        nullable=False,
    )

    # Populated by the analysis pipeline (later phases).
    risk_tier: Mapped[RiskTier | None] = mapped_column(
        SAEnum(RiskTier, native_enum=False, length=16), nullable=True
    )
    current_risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    applicant: Mapped[User] = relationship(  # noqa: F821
        back_populates="applications", foreign_keys=[applicant_id]
    )
    documents: Mapped[list[Document]] = relationship(  # noqa: F821
        back_populates="application", foreign_keys="Document.application_id"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Application {self.application_number} status={self.status.value}>"
