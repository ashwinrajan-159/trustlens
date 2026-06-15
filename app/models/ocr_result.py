"""OCR output for a document. One current row per document (re-runs supersede).

``raw_text`` is operational text used by downstream extraction — it is NOT logged and
not returned verbatim in API responses (only presence/length + confidence are exposed).
"""
from __future__ import annotations

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin


class OcrResult(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "ocr_results"

    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id"), index=True, nullable=False
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pages_data: Mapped[list | None] = mapped_column(JSON, nullable=True)
    engine: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<OcrResult doc={self.document_id} conf={self.confidence_score:.2f}>"
