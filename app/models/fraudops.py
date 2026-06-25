"""Phase 12 — fraud-ops closed-loop models.

The investigation/review records are the immutable human inputs; the knowledge-base
counters (`fraud_patterns`, `signal_performance`) are **recomputable projections** derived
from immutable `pattern_case_links` + review decisions — never the source of truth. The
versioned `signal_weight_config` makes the deterministic risk engine's weights data-driven
and governed (propose → approve → activate), keeping every historical score reproducible.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import (
    FPReasonCode,
    ReportRecommendation,
    ReviewDecision,
    SignalSeverity,
    WeightConfigStatus,
)


class InvestigationReport(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "investigation_reports"

    alert_id: Mapped[str] = mapped_column(String(36), ForeignKey("fraud_alerts.id"), index=True, nullable=False)
    case_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("investigation_cases.id"), nullable=True)
    underwriter_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)

    investigation_summary: Mapped[str] = mapped_column(Text, nullable=False)
    findings: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    recommendation: Mapped[ReportRecommendation] = mapped_column(
        SAEnum(ReportRecommendation, native_enum=False, length=32), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<InvestigationReport alert={self.alert_id} rec={self.recommendation.value}>"


class ReviewDecisionRecord(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "review_decisions"

    report_id: Mapped[str] = mapped_column(String(36), ForeignKey("investigation_reports.id"), index=True, nullable=False)
    alert_id: Mapped[str] = mapped_column(String(36), ForeignKey("fraud_alerts.id"), index=True, nullable=False)
    reviewer_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)  # MUST differ from underwriter
    decision: Mapped[ReviewDecision] = mapped_column(
        SAEnum(ReviewDecision, native_enum=False, length=24), index=True, nullable=False
    )
    comments: Mapped[str] = mapped_column(Text, nullable=False, default="")
    fp_reason_code: Mapped[FPReasonCode | None] = mapped_column(
        SAEnum(FPReasonCode, native_enum=False, length=32), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ReviewDecision report={self.report_id} {self.decision.value}>"


class FalsePositiveRecord(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Structured FP capture for analytics. One per FALSE_POSITIVE review decision."""

    __tablename__ = "false_positive_records"

    alert_id: Mapped[str] = mapped_column(String(36), ForeignKey("fraud_alerts.id"), index=True, nullable=False)
    review_decision_id: Mapped[str] = mapped_column(String(36), ForeignKey("review_decisions.id"), nullable=False)
    application_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    signal_names: Mapped[list | None] = mapped_column(JSON, nullable=True)   # signals implicated
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    analyst_explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    fp_reason_code: Mapped[FPReasonCode] = mapped_column(
        SAEnum(FPReasonCode, native_enum=False, length=32), nullable=False
    )
    final_outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)


class FraudPattern(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A learned fraud pattern. Counters are recomputable projections over pattern_case_links."""

    __tablename__ = "fraud_patterns"

    name: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    category: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    severity: Mapped[SignalSeverity] = mapped_column(
        SAEnum(SignalSeverity, native_enum=False, length=16), default=SignalSeverity.MEDIUM, nullable=False
    )
    # Explainable definition, e.g. {"category": "IDENTITY", "signal_types": [...]}.
    detection_logic: Mapped[dict] = mapped_column(JSON, nullable=False)

    # Projections (recomputed from pattern_case_links):
    occurrences: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confirmed_cases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    false_positive_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pattern_confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FraudPattern {self.name} conf={self.pattern_confidence:.2f}>"


class PatternCaseLink(UUIDMixin, TimestampMixin, Base):
    """Immutable evidence linking a pattern to a reviewed alert/application + its outcome.
    The (pattern_id, alert_id) uniqueness keeps learning idempotent (no double-counting)."""

    __tablename__ = "pattern_case_links"
    __table_args__ = (UniqueConstraint("pattern_id", "alert_id", name="uq_pattern_alert"),)

    pattern_id: Mapped[str] = mapped_column(String(36), ForeignKey("fraud_patterns.id"), index=True, nullable=False)
    alert_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    application_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    outcome: Mapped[ReviewDecision] = mapped_column(
        SAEnum(ReviewDecision, native_enum=False, length=24), nullable=False
    )
    signal_names: Mapped[list | None] = mapped_column(JSON, nullable=True)


class SignalPerformance(TimestampMixin, Base):
    """Per-signal precision projection with sample-size discipline + Wilson CI."""

    __tablename__ = "signal_performance"

    signal_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    times_triggered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confirmed_fraud_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    false_positive_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    precision_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    sample_sufficient: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    precision_ci_low: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    precision_ci_high: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    last_updated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SignalWeightConfig(UUIDMixin, TimestampMixin, Base):
    """Versioned signal-weight set. Exactly one ACTIVE row drives the risk engine; prior
    versions are retained so historical risk scores remain reproducible."""

    __tablename__ = "signal_weight_config"

    version: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    weights: Mapped[dict] = mapped_column(JSON, nullable=False)   # {signal_type: weight}
    status: Mapped[WeightConfigStatus] = mapped_column(
        SAEnum(WeightConfigStatus, native_enum=False, length=16),
        default=WeightConfigStatus.DRAFT, index=True, nullable=False,
    )
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SignalWeightConfig v{self.version} {self.status.value}>"
