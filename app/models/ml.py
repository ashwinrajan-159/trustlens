"""ML platform tables (Phase 9). All local — ML is a *second opinion*, never the
system of record (the deterministic engine + SHAP own explainability).

- ``MLFeatureSnapshot`` — the numeric feature vector for an application at a point in time.
- ``MLLabel`` — training labels harvested from analyst decisions/feedback (fraud=1/legit=0).
- ``MLModel`` — model registry with governance status, metrics and champion flag.
- ``MLPrediction`` — per-application inference output + SHAP top features + latency.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import MLLabelSource, MLModelStatus


class MLFeatureSnapshot(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "ml_feature_snapshots"

    application_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("applications.id"), index=True, nullable=False
    )
    features: Mapped[dict] = mapped_column(JSON, nullable=False)
    feature_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class MLLabel(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "ml_labels"

    application_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("applications.id"), index=True, nullable=False
    )
    label: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 = fraud, 0 = legitimate
    source: Mapped[MLLabelSource] = mapped_column(
        SAEnum(MLLabelSource, native_enum=False, length=32), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class MLModel(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "ml_models"

    name: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    algorithm: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[MLModelStatus] = mapped_column(
        SAEnum(MLModelStatus, native_enum=False, length=16),
        default=MLModelStatus.TRAINED, index=True, nullable=False,
    )
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    feature_names: Mapped[list | None] = mapped_column(JSON, nullable=True)
    artifact_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    training_samples: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    is_champion: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MLModel {self.name} v{self.version} {self.status.value}>"


class MLPrediction(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "ml_predictions"

    application_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("applications.id"), index=True, nullable=False
    )
    model_id: Mapped[str] = mapped_column(String(36), ForeignKey("ml_models.id"), nullable=False)
    fraud_probability: Mapped[float] = mapped_column(Float, nullable=False)
    risk_tier: Mapped[str] = mapped_column(String(16), nullable=False)
    shap_top: Mapped[list | None] = mapped_column(JSON, nullable=True)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MLPrediction {self.application_id} p={self.fraud_probability:.3f}>"
