"""``run_document_forensics`` — image/PDF forensics pipeline step (Phase 13).

Runs the ``app.forensics`` intelligence layer on one document and persists its
findings as ordinary ``FraudSignal`` rows (DOCUMENT scope) so the existing,
severity-driven scorer folds them in with no scorer changes. Also records each
page's perceptual hash in ``document_fingerprints`` so a *later* application that
re-submits the same supporting document trips ``FORENSIC_DOCUMENT_REUSED_ACROSS_APPS``.

Design notes
------------
* ``app.forensics.run_forensics`` is synchronous (OpenCV/PIL analyzers), but this
  app is async SQLAlchemy. We therefore PRE-LOAD existing fingerprints into an
  in-memory ``_PreloadedHashStore`` before the sync run, collect new fingerprints
  in memory during it, then async-persist them afterwards. No async DB call ever
  happens inside the sync pipeline.
* Idempotent: prior forensic signals for this document (engine_version
  ``forensics_1.0``) are retired before the fresh set is written.
* Best-effort: any failure is logged and swallowed — forensics must never break
  the core analysis pipeline.
* ``INFO`` forensic severity maps to ``LOW`` (the platform has no INFO tier), and
  zero-weight informational signals (e.g. seal-auth-unavailable) are not persisted
  as scoreable signals — keeping weak hits from flooding the scorer.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.logging import get_logger
from app.database import SessionFactory
from app.models.base import _utcnow
from app.models.document import Document
from app.models.document_fingerprint import DocumentFingerprint
from app.models.enums import FraudSignalType, SignalScope, SignalSeverity
from app.models.fraud_signal import FraudSignal
from app.worker import celery_app

log = get_logger(__name__)

FORENSICS_ENGINE_VERSION = "forensics_1.0"

# Forensic INFO has no platform tier → fold into LOW.
_SEVERITY_MAP = {
    "INFO": SignalSeverity.LOW,
    "LOW": SignalSeverity.LOW,
    "MEDIUM": SignalSeverity.MEDIUM,
    "HIGH": SignalSeverity.HIGH,
    "CRITICAL": SignalSeverity.CRITICAL,
}


class _PreloadedHashStore:
    """In-memory HashStore: compares against fingerprints pre-loaded from the DB,
    buffers new ones for the caller to persist after the (sync) forensics run."""

    def __init__(self, rows: list[dict]):
        self._rows = list(rows)          # existing {application_id, phash_hex}
        self.pending: list[dict] = []    # new fingerprints to persist

    def find_similar(self, phash_hex: str, max_distance: int) -> list[dict]:
        target = int(phash_hex, 16)
        out = []
        for r in (*self._rows, *self.pending):
            try:
                if bin(target ^ int(r["phash_hex"], 16)).count("1") <= max_distance:
                    out.append(r)
            except (KeyError, ValueError):
                continue
        return out

    def save(self, *, document_id: str, application_id: str, phash_hex: str,
             extra: dict | None = None) -> None:
        self.pending.append({
            "document_id": document_id, "application_id": application_id,
            "phash_hex": phash_hex, "extra": extra or {},
        })


def _to_fraud_signal_type(code: str) -> FraudSignalType:
    try:
        return FraudSignalType(code)
    except ValueError:
        return FraudSignalType.FORENSIC_DOCUMENT_ANOMALY


async def run_document_forensics_async(document_id: str, *, session_factory=None) -> dict:
    sf = session_factory or SessionFactory
    async with sf() as session:
        document = (
            await session.execute(select(Document).where(Document.id == document_id))
        ).scalar_one_or_none()
        if document is None:
            return {"status": "missing", "document_id": document_id}

        # Download bytes from object storage.
        from app.services.storage import StorageService
        try:
            raw = await StorageService().download(document.storage_key)
        except Exception as exc:  # noqa: BLE001
            log.warning("forensics.download_failed", document_id=document_id, error=str(exc))
            return {"status": "download_failed", "document_id": document_id}

        mime = document.content_type or ""
        is_pdf = mime == "application/pdf" or (document.original_filename or "").lower().endswith(".pdf")
        fitz_doc = None
        if is_pdf:
            try:
                import fitz
                fitz_doc = fitz.open(stream=raw, filetype="pdf")
            except Exception:
                fitz_doc = None

        # Pre-load existing fingerprints (bounded) for cross-application reuse.
        rows = (
            await session.execute(
                select(
                    DocumentFingerprint.application_id,
                    DocumentFingerprint.phash_hex,
                    DocumentFingerprint.document_id,
                )
            )
        ).all()
        store = _PreloadedHashStore(
            [{"application_id": r[0], "phash_hex": r[1], "document_id": r[2]} for r in rows]
        )

        # Run the (synchronous) forensics pipeline.
        from app.forensics import run_forensics
        result = run_forensics(
            document_id=document.id, application_id=document.application_id,
            filename=document.original_filename, mime=mime,
            raw_bytes=raw, hash_store=store, fitz_doc=fitz_doc, context={},
        )

        # Idempotent regenerate: retire this document's prior forensic signals.
        prior = (
            await session.execute(
                select(FraudSignal).where(
                    FraudSignal.document_id == document_id,
                    FraudSignal.engine_version == FORENSICS_ENGINE_VERSION,
                    FraudSignal.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        for p in prior:
            p.deleted_at = _utcnow()

        persisted = 0
        for s in result.signals:
            if s.effective_weight <= 0:
                continue  # informational (zero-weight) — keep out of the scorer
            session.add(
                FraudSignal(
                    application_id=document.application_id,
                    document_id=document.id,
                    signal_type=_to_fraud_signal_type(s.code),
                    severity=_SEVERITY_MAP.get(s.severity.value, SignalSeverity.LOW),
                    signal_scope=SignalScope.DOCUMENT,
                    description=f"{s.title}: {' '.join(s.reasons)}".strip(),
                    evidence={
                        **(s.evidence or {}),
                        "forensic_code": s.code,
                        "confidence_tier": s.confidence.value,
                        "analyzer": s.analyzer,
                    },
                    confidence=s.effective_weight,
                    rule_name=f"forensics.{s.analyzer or 'pipeline'}",
                    engine_version=FORENSICS_ENGINE_VERSION,
                    source_document_ids=[document.id],
                )
            )
            persisted += 1

        # Persist new perceptual-hash fingerprints (cross-application reuse memory).
        for fp in store.pending:
            session.add(
                DocumentFingerprint(
                    document_id=fp["document_id"],
                    application_id=fp["application_id"],
                    phash_hex=fp["phash_hex"],
                    page=int((fp.get("extra") or {}).get("page", 0)),
                    extra=fp.get("extra"),
                )
            )

        await session.commit()
        log.info(
            "forensics.complete", document_id=document_id, kind=result.kind.value,
            signals=persisted, subscore=result.forensics_subscore,
            skipped=len(result.skipped), errors=len(result.errors),
        )
        return {
            "status": "analyzed", "document_id": document_id, "kind": result.kind.value,
            "signals": persisted, "subscore": result.forensics_subscore,
            "errors": result.errors,
        }


@celery_app.task(
    name="app.tasks.forensics.run_document_forensics",
    bind=True, max_retries=3, default_retry_delay=10,
)
def run_document_forensics(self, document_id: str) -> dict:
    try:
        return asyncio.run(run_document_forensics_async(document_id))
    except Exception as exc:  # pragma: no cover - retry path needs a live broker
        raise self.retry(exc=exc) from exc
