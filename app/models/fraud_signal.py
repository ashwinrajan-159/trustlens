"""A single fraud signal — explainable evidence anchored to an application.

Produced by converting a fraud-engine ``RuleResult`` into a persisted row. ``evidence``
holds the rule's structured justification (no raw PII). ``signal_scope`` records which
layer produced it (DOCUMENT here in Phase 3b; CROSS_DOCUMENT/IDENTITY/etc. in later phases).
"""
from __future__ import annotations

from sqlalchemy import JSON, Boolean, Float, ForeignKey, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import FraudSignalType, SignalScope, SignalSeverity


class FraudSignal(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "fraud_signals"

    application_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("applications.id"), index=True, nullable=False
    )
    document_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("documents.id"), index=True, nullable=True
    )

    signal_type: Mapped[FraudSignalType] = mapped_column(
        SAEnum(FraudSignalType, native_enum=False, length=48), nullable=False
    )
    severity: Mapped[SignalSeverity] = mapped_column(
        SAEnum(SignalSeverity, native_enum=False, length=16), index=True, nullable=False
    )
    signal_scope: Mapped[SignalScope] = mapped_column(
        SAEnum(SignalScope, native_enum=False, length=16), default=SignalScope.DOCUMENT, nullable=False
    )

    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)

    source_document_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FraudSignal {self.signal_type.value} {self.severity.value}>"
