"""Resolved identity for an application — consolidated across its documents.

One current profile per application (re-resolution supersedes). Sensitive resolved
values are encrypted at rest; masked forms are kept for display. ``indicators`` holds
the synthetic-identity reasoning (counts/flags only — never raw PII).
"""
from __future__ import annotations

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.encryption import EncryptedString
from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin


class IdentityProfile(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "identity_profiles"

    application_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("applications.id"), index=True, nullable=False
    )

    resolved_name: Mapped[str | None] = mapped_column(EncryptedString(512), nullable=True)
    resolved_name_masked: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pan: Mapped[str | None] = mapped_column(EncryptedString(64), nullable=True)
    pan_masked: Mapped[str | None] = mapped_column(String(32), nullable=True)
    aadhaar_masked: Mapped[str | None] = mapped_column(String(32), nullable=True)
    dob: Mapped[str | None] = mapped_column(EncryptedString(32), nullable=True)

    distinct_name_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    distinct_pan_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    distinct_dob_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    synthetic_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    is_synthetic_suspected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    indicators: Mapped[list | None] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<IdentityProfile app={self.application_id} synthetic={self.is_synthetic_suspected}>"
