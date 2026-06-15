"""Graph-analysis snapshot for an application (Phase 7).

Records the outcome of the entity-relationship graph analysis: how many other
applications this one is connected to (via shared PAN / account / property / identity),
the fraud-ring it belongs to (if any), and a derived graph risk score. One current row
per application (re-analysis supersedes). No PII — counts + IDs only.
"""
from __future__ import annotations

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin


class GraphAnalysis(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "graph_analyses"

    application_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("applications.id"), index=True, nullable=False
    )
    graph_risk_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    fraud_connections_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    shared_pan_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    shared_account_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    shared_property_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    ring_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    in_fraud_ring: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    connected_application_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<GraphAnalysis app={self.application_id} ring={self.in_fraud_ring}>"
