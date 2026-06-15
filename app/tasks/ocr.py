"""``run_ocr_pipeline`` — first step of the analysis pipeline (Phase 2).

Design (carried from the spec):
- Celery task is a thin sync wrapper that runs an async implementation via ``asyncio.run``
  (avoids prefork event-loop reuse issues).
- Idempotent / safely re-runnable: a re-run soft-deletes prior OCR results for the
  document before writing the new one, and an already-PROCESSED document with a result
  short-circuits.
- De-dup by ``checksum_sha256`` using an ordered ``limit(1)`` (a checksum legitimately
  recurs — never ``scalar_one_or_none``): identical bytes reuse the prior OCR text.
- Status flows QUEUED → PROCESSING → PROCESSED, or → FAILED on unrecoverable error.
- The async impl accepts an optional session factory + storage so it is unit-testable
  without a broker, real DB engine, or MinIO.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.logging import get_logger
from app.database import SessionFactory
from app.models.document import Document
from app.models.enums import DocumentStatus
from app.models.ocr_result import OcrResult
from app.services import ocr as ocr_service
from app.services.storage import StorageService
from app.worker import celery_app

log = get_logger(__name__)


async def _reuse_existing_text(session, document: Document) -> OcrResult | None:
    """Find a prior OCR result for another document with the same checksum (de-dup)."""
    stmt = (
        select(OcrResult)
        .join(Document, OcrResult.document_id == Document.id)
        .where(
            Document.checksum_sha256 == document.checksum_sha256,
            Document.id != document.id,
            OcrResult.deleted_at.is_(None),
        )
        .order_by(OcrResult.created_at.asc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def run_ocr_pipeline_async(
    document_id: str, *, session_factory=None, storage: StorageService | None = None
) -> dict:
    sf = session_factory or SessionFactory
    store = storage or StorageService()

    async with sf() as session:
        document = (
            await session.execute(select(Document).where(Document.id == document_id))
        ).scalar_one_or_none()
        if document is None:
            log.warning("ocr.document_missing", document_id=document_id)
            return {"status": "missing", "document_id": document_id}

        # Idempotency: already done and has a current result → no-op.
        if document.status == DocumentStatus.PROCESSED:
            existing = (
                await session.execute(
                    select(OcrResult).where(
                        OcrResult.document_id == document.id,
                        OcrResult.deleted_at.is_(None),
                    )
                )
            ).scalars().first()
            if existing:
                return {"status": "already_processed", "document_id": document_id}

        document.status = DocumentStatus.PROCESSING
        await session.commit()

        try:
            # De-dup: reuse identical-bytes OCR if we've already done it.
            reuse = await _reuse_existing_text(session, document)
            if reuse is not None:
                out = ocr_service.OcrOutput(
                    text=reuse.raw_text,
                    confidence=reuse.confidence_score,
                    page_count=reuse.page_count,
                    engine=f"{reuse.engine}+dedup",
                    model_version=reuse.model_version,
                    pages=reuse.pages_data or [],
                )
            else:
                data = await store.download(document.storage_key)
                out = ocr_service.run_ocr(data, document.content_type)

            # Re-runnable: retire any prior results for this document first.
            prior = (
                await session.execute(
                    select(OcrResult).where(
                        OcrResult.document_id == document.id,
                        OcrResult.deleted_at.is_(None),
                    )
                )
            ).scalars().all()
            from app.models.base import _utcnow

            for p in prior:
                p.deleted_at = _utcnow()

            result = OcrResult(
                document_id=document.id,
                raw_text=out.text,
                confidence_score=out.confidence,
                page_count=out.page_count,
                pages_data=out.pages,
                engine=out.engine,
                model_version=out.model_version,
            )
            session.add(result)
            document.status = DocumentStatus.PROCESSED
            await session.commit()
            log.info(
                "ocr.processed",
                document_id=document_id,
                engine=out.engine,
                confidence=round(out.confidence, 3),
                pages=out.page_count,
            )
            # Chain extraction (Phase 3). Failure here must NOT undo a successful OCR —
            # extraction is independently re-runnable, so log and continue.
            try:
                from app.tasks.extraction import extract_entities_async

                await extract_entities_async(document_id, session_factory=sf)
            except Exception as exc:  # noqa: BLE001
                log.error("ocr.extraction_chain_failed", document_id=document_id, error=str(exc))
            return {
                "status": "processed",
                "document_id": document_id,
                "confidence": out.confidence,
                "page_count": out.page_count,
            }
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            document.status = DocumentStatus.FAILED
            await session.commit()
            log.error("ocr.failed", document_id=document_id, error=str(exc))
            raise


@celery_app.task(
    name="app.tasks.ocr.run_ocr_pipeline",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    queue="ocr",
)
def run_ocr_pipeline(self, document_id: str) -> dict:
    try:
        return asyncio.run(run_ocr_pipeline_async(document_id))
    except Exception as exc:  # pragma: no cover - retry path needs a live broker
        raise self.retry(exc=exc) from exc


def dispatch_ocr(document_id: str) -> None:
    """Best-effort enqueue. If the broker is down the document stays QUEUED and a
    reconciliation sweep / manual re-run can pick it up later — never fail the upload."""
    from app.config import settings

    if settings.is_test:
        return  # tests exercise the pipeline directly, not via a broker
    try:
        run_ocr_pipeline.delay(document_id)
        log.info("ocr.dispatched", document_id=document_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("ocr.dispatch_failed", document_id=document_id, error=str(exc))
