"""``extract_entities`` — pipeline step after OCR (Phase 3 extraction).

Reads the document's current OCR text, runs the deterministic extraction service, and
persists ``ExtractedEntity`` rows. Sensitive values are encrypted at rest (the model's
``EncryptedString``) and a masked form is stored for display. Idempotent: a re-run
soft-deletes the document's prior entities before regenerating.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.encryption import mask_aadhaar, mask_account, mask_generic, mask_pan
from app.core.logging import get_logger
from app.database import SessionFactory
from app.models.base import _utcnow
from app.models.document import Document
from app.models.enums import SENSITIVE_ENTITY_TYPES, EntityType
from app.models.extracted_entity import ExtractedEntity
from app.models.ocr_result import OcrResult
from app.services import extraction
from app.worker import celery_app

log = get_logger(__name__)

_MASKERS = {
    EntityType.PAN: mask_pan,
    EntityType.AADHAAR: mask_aadhaar,
    EntityType.ACCOUNT_NUMBER: mask_account,
}


def _masked(entity_type: EntityType, value: str) -> str | None:
    masker = _MASKERS.get(entity_type)
    if masker:
        return masker(value)
    # DOB / ADDRESS and any other sensitive type → generic tail-mask.
    return mask_generic(value, keep=2)


async def extract_entities_async(document_id: str, *, session_factory=None) -> dict:
    sf = session_factory or SessionFactory
    async with sf() as session:
        document = (
            await session.execute(select(Document).where(Document.id == document_id))
        ).scalar_one_or_none()
        if document is None:
            return {"status": "missing", "document_id": document_id}

        ocr = (
            await session.execute(
                select(OcrResult)
                .where(OcrResult.document_id == document_id, OcrResult.deleted_at.is_(None))
                .order_by(OcrResult.created_at.desc())
                .limit(1)
            )
        ).scalars().first()
        if ocr is None:
            # OCR hasn't run yet — defer; this step is safely re-runnable.
            return {"status": "deferred_no_ocr", "document_id": document_id}

        # Idempotent regenerate: retire prior entities for this document.
        prior = (
            await session.execute(
                select(ExtractedEntity).where(
                    ExtractedEntity.document_id == document_id,
                    ExtractedEntity.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        for p in prior:
            p.deleted_at = _utcnow()

        drafts = extraction.extract(document.document_type, ocr.raw_text)
        for d in drafts:
            is_sensitive = d.entity_type in SENSITIVE_ENTITY_TYPES
            session.add(
                ExtractedEntity(
                    document_id=document.id,
                    application_id=document.application_id,
                    entity_type=d.entity_type,
                    value=d.value,  # EncryptedString encrypts at rest
                    masked_value=_masked(d.entity_type, d.value) if is_sensitive else d.value,
                    is_sensitive=is_sensitive,
                    confidence=d.confidence,
                    extraction_method=d.method,
                    source_page=d.source_page,
                )
            )
        await session.commit()
        log.info("extraction.done", document_id=document_id, count=len(drafts))

    # Chain the fraud engine (Phase 3b). Best-effort: extraction already committed.
    try:
        from app.tasks.fraud import run_fraud_engine_async

        await run_fraud_engine_async(document_id, session_factory=sf)
    except Exception as exc:  # noqa: BLE001
        log.error("extraction.fraud_chain_failed", document_id=document_id, error=str(exc))
    return {"status": "extracted", "document_id": document_id, "count": len(drafts)}


@celery_app.task(name="app.tasks.extraction.extract_entities", bind=True, max_retries=3, default_retry_delay=10)
def extract_entities(self, document_id: str) -> dict:
    try:
        return asyncio.run(extract_entities_async(document_id))
    except Exception as exc:  # pragma: no cover - retry path needs a live broker
        raise self.retry(exc=exc) from exc
