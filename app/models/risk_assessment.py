"""Risk assessment for an application — the auditable scoring snapshot.

``reasons`` is the full weighted breakdown produced by the deterministic scorer, so any
score can be explained signal-by-signal to a regulator or analyst.
"""
from __future__ import annotations

from sqlalchemy import JSON, Float, ForeignKey, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import RiskTier


class RiskAssessment(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "risk_assessments"

    application_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("applications.id"), index=True, nullable=False
    )
    total_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    risk_tier: Mapped[RiskTier] = mapped_column(
        SAEnum(RiskTier, native_enum=False, length=16), nullable=False
    )
    reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)
    by_category: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    engine_version: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    # Governed weight set in force when this score was computed (None = built-in defaults).
    # Persisted so a historical score is reproducible with the weights of its time.
    weight_config_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RiskAssessment {self.total_score} {self.risk_tier.value}>"
