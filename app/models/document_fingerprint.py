"""Perceptual-hash fingerprints of uploaded document pages.

Append-only history that powers cross-application document-reuse detection
(``app/forensics`` SimilarityForensics). Each row is one page's pHash; the
forensics layer compares a new page's pHash against all stored fingerprints
(bounded Hamming distance) to surface the same supporting document recycled
across different loan applications — a coordinated-fraud signal.

No PII: a perceptual hash is a non-reversible 256-bit summary, not the image.
"""
from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class DocumentFingerprint(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "document_fingerprints"

    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id"), index=True, nullable=False
    )
    application_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("applications.id"), index=True, nullable=False
    )
    # Hex perceptual hash (imagehash.phash, hash_size=16 → 64 hex chars).
    phash_hex: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    page: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DocumentFingerprint doc={self.document_id} page={self.page}>"
