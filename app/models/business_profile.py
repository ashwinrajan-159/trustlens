"""Resolved business/financial profile for an application (Phase 6).

One current profile per application (re-validation supersedes). Reconciled revenue/profit
figures from ITR + GST returns.
"""
from __future__ import annotations

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin


class BusinessProfile(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "business_profiles"

    application_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("applications.id"), index=True, nullable=False
    )
    itr_revenue: Mapped[float | None] = mapped_column(Float, nullable=True)
    gst_revenue: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    revenue_gap_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<BusinessProfile app={self.application_id}>"
