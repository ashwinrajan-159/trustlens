"""Uploaded document. Stores the object KEY in MinIO/S3 — never a full URL.

Presigned download URLs are generated on demand with a short TTL. ``checksum_sha256``
is indexed for de-duplication; note multiple documents can legitimately share a
checksum, so lookups must use ordered ``limit(1)``, never ``scalar_one_or_none``.
"""
from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import DocumentStatus, DocumentType


class Document(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "documents"

    application_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("applications.id"), index=True, nullable=False
    )
    document_type: Mapped[DocumentType] = mapped_column(
        SAEnum(DocumentType, native_enum=False, length=32), nullable=False
    )

    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), index=True, nullable=False)

    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_current_version: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    status: Mapped[DocumentStatus] = mapped_column(
        SAEnum(DocumentStatus, native_enum=False, length=16),
        default=DocumentStatus.QUEUED,
        index=True,
        nullable=False,
    )
    uploaded_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )

    application: Mapped[Application] = relationship(  # noqa: F821
        back_populates="documents", foreign_keys=[application_id]
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Document {self.document_type.value} status={self.status.value}>"
