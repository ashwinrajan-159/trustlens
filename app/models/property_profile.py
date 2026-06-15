"""Resolved property/collateral profile for an application (Phase 6).

One current profile per application (re-validation supersedes). Survey numbers and
amounts are not PII, so stored in clear; ``duplicate_collateral_app_ids`` records other
applications pledging the same collateral.
"""
from __future__ import annotations

from sqlalchemy import JSON, Boolean, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin


class PropertyProfile(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "property_profiles"

    application_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("applications.id"), index=True, nullable=False
    )
    survey_numbers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    area: Mapped[float | None] = mapped_column(Float, nullable=True)
    sale_consideration: Mapped[float | None] = mapped_column(Float, nullable=True)
    valuation: Mapped[float | None] = mapped_column(Float, nullable=True)
    valuation_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_inflated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    duplicate_collateral_app_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PropertyProfile app={self.application_id} inflated={self.is_inflated}>"
