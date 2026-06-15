"""A single structured field extracted from a document's OCR text.

Anchored to both the document (provenance) and the application (the case it feeds).
Sensitive values (PAN, Aadhaar, account no., DOB, address) are stored **encrypted** in
``value`` via the ``EncryptedString`` decorator; ``masked_value`` holds the safe
display form returned in API responses. Non-sensitive values are stored in clear.
"""
from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.encryption import EncryptedString
from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import EntityType, ExtractionMethod


class ExtractedEntity(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "extracted_entities"

    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id"), index=True, nullable=False
    )
    application_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("applications.id"), index=True, nullable=False
    )

    entity_type: Mapped[EntityType] = mapped_column(
        SAEnum(EntityType, native_enum=False, length=32), nullable=False
    )
    # Encrypted at rest; decrypts transparently on read. May be clear for non-PII.
    value: Mapped[str | None] = mapped_column(EncryptedString(1024), nullable=True)
    masked_value: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    extraction_method: Mapped[ExtractionMethod] = mapped_column(
        SAEnum(ExtractionMethod, native_enum=False, length=16),
        default=ExtractionMethod.REGEX,
        nullable=False,
    )
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ExtractedEntity {self.entity_type.value} masked={self.masked_value}>"
