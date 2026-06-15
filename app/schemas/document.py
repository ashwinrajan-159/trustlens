"""Document schemas. Responses expose storage_key (not raw URLs); downloads use
short-lived presigned URLs returned from a dedicated endpoint."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import DocumentStatus, DocumentType, EntityType, ExtractionMethod


class DocumentPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    application_id: str
    document_type: DocumentType
    original_filename: str
    content_type: str
    file_size: int
    checksum_sha256: str
    version: int
    is_current_version: bool
    status: DocumentStatus
    created_at: datetime


class OcrSummary(BaseModel):
    """OCR outcome WITHOUT the raw text (PII-safe): presence + quality only."""

    engine: str
    confidence_score: float
    page_count: int
    has_text: bool
    char_count: int


class DocumentDetail(DocumentPublic):
    ocr: OcrSummary | None = None


class ExtractedEntityPublic(BaseModel):
    """An extracted field for display. ``value`` is masked for sensitive types; raw PII
    is never returned here (it stays encrypted at rest)."""

    id: str
    document_id: str
    entity_type: EntityType
    value: str | None  # masked when is_sensitive
    is_sensitive: bool
    confidence: float
    extraction_method: ExtractionMethod
    source_page: int | None


class PresignedDownloadResponse(BaseModel):
    url: str
    expires_in_seconds: int
