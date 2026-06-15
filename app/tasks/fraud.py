"""``run_fraud_engine`` + ``compute_risk_assessment`` — pipeline steps after extraction.

- ``run_fraud_engine``: builds a pre-fetched ``RuleContext`` for one document (OCR
  confidence, extracted entities, duplicate-checksum flag), runs the standalone engine,
  and persists the resulting ``FraudSignal`` rows. Idempotent: prior DOCUMENT-scope
  signals for the document are soft-deleted before regenerating.
- ``compute_risk_assessment``: aggregates all live signals for the application, scores
  them deterministically, writes a ``RiskAssessment`` and updates the application's tier.

Both run inside ``asyncio.run`` via Celery wrappers and accept an injectable session
factory so they are unit-testable without a broker or real DB engine.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.logging import get_logger
from app.database import SessionFactory
from app.fraud_engine import RuleContext, RuleResult, run_rules, score
from app.models.application import Application
from app.models.base import _utcnow
from app.models.document import Document
from app.models.enums import (
    FraudSignalType,
    RiskTier,
    SignalScope,
    SignalSeverity,
)
from app.models.extracted_entity import ExtractedEntity
from app.models.fraud_signal import FraudSignal
from app.models.ocr_result import OcrResult
from app.models.risk_assessment import RiskAssessment
from app.worker import celery_app

log = get_logger(__name__)

ENGINE_VERSION = "1.0.0"


async def _build_context(session, document: Document) -> RuleContext:
    ocr = (
        await session.execute(
            select(OcrResult)
            .where(OcrResult.document_id == document.id, OcrResult.deleted_at.is_(None))
            .order_by(OcrResult.created_at.desc())
            .limit(1)
        )
    ).scalars().first()

    entity_rows = (
        await session.execute(
            select(ExtractedEntity).where(
                ExtractedEntity.document_id == document.id,
                ExtractedEntity.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    entities: dict[str, list[str]] = {}
    for e in entity_rows:
        if e.value is not None:  # decrypted transparently on read
            entities.setdefault(e.entity_type.value, []).append(e.value)

    # Duplicate-checksum detection (ordered limit(1) — duplicates are expected).
    dup = (
        await session.execute(
            select(Document.id)
            .where(
                Document.checksum_sha256 == document.checksum_sha256,
                Document.id != document.id,
                Document.deleted_at.is_(None),
            )
            .order_by(Document.created_at.asc())
            .limit(1)
        )
    ).scalars().first()

    return RuleContext(
        document_id=document.id,
        document_type=document.document_type.value,
        ocr_confidence=ocr.confidence_score if ocr else None,
        ocr_text=ocr.raw_text if ocr else "",
        entities=entities,
        duplicate_of_document_id=dup,
    )


async def run_fraud_engine_async(document_id: str, *, session_factory=None) -> dict:
    sf = session_factory or SessionFactory
    async with sf() as session:
        document = (
            await session.execute(select(Document).where(Document.id == document_id))
        ).scalar_one_or_none()
        if document is None:
            return {"status": "missing", "document_id": document_id}

        ctx = await _build_context(session, document)
        results: list[RuleResult] = run_rules(ctx)

        # Idempotent regenerate: retire this document's prior DOCUMENT-scope signals.
        prior = (
            await session.execute(
                select(FraudSignal).where(
                    FraudSignal.document_id == document_id,
                    FraudSignal.signal_scope == SignalScope.DOCUMENT,
                    FraudSignal.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        for p in prior:
            p.deleted_at = _utcnow()

        for r in results:
            session.add(
                FraudSignal(
                    application_id=document.application_id,
                    document_id=document.id,
                    signal_type=FraudSignalType(r.signal_type),
                    severity=SignalSeverity(r.severity),
                    signal_scope=SignalScope.DOCUMENT,
                    description=r.description,
                    evidence=r.evidence,
                    confidence=r.confidence,
                    rule_name=r.rule_name,
                    engine_version=ENGINE_VERSION,
                    source_document_ids=[document.id],
                )
            )
        await session.commit()
        log.info("fraud.signals_generated", document_id=document_id, count=len(results))
        application_id = document.application_id

    # Chain identity resolution (Phase 4), which in turn recomputes risk (best-effort).
    try:
        from app.tasks.identity import run_identity_resolution_async

        await run_identity_resolution_async(application_id, session_factory=sf)
    except Exception as exc:  # noqa: BLE001
        log.error("fraud.identity_chain_failed", application_id=application_id, error=str(exc))
    return {"status": "scored", "document_id": document_id, "signals": len(results)}


async def compute_risk_assessment_async(application_id: str, *, session_factory=None) -> dict:
    sf = session_factory or SessionFactory
    async with sf() as session:
        application = (
            await session.execute(select(Application).where(Application.id == application_id))
        ).scalar_one_or_none()
        if application is None:
            return {"status": "missing", "application_id": application_id}

        signals = (
            await session.execute(
                select(FraudSignal).where(
                    FraudSignal.application_id == application_id,
                    FraudSignal.deleted_at.is_(None),
                )
            )
        ).scalars().all()

        results = [
            RuleResult(
                signal_type=s.signal_type.value,
                severity=s.severity.value,
                description=s.description,
                rule_name=s.rule_name,
                confidence=s.confidence,
                evidence=s.evidence or {},
            )
            for s in signals
        ]
        outcome = score(results)

        # Idempotent: retire prior assessments, write the fresh one.
        prior = (
            await session.execute(
                select(RiskAssessment).where(
                    RiskAssessment.application_id == application_id,
                    RiskAssessment.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        for p in prior:
            p.deleted_at = _utcnow()

        session.add(
            RiskAssessment(
                application_id=application_id,
                total_score=outcome.total_score,
                risk_tier=RiskTier(outcome.risk_tier),
                reasons=outcome.reasons,
                by_category=outcome.by_category,
                engine_version=ENGINE_VERSION,
            )
        )
        application.current_risk_score = outcome.total_score
        application.risk_tier = RiskTier(outcome.risk_tier)

        # Emit RISK_CALCULATED (transactional outbox — committed with the assessment).
        from app.core.security import new_id
        from app.events import schemas as ev
        from app.events.service import publish_pending, stage

        stage(session, ev.risk_calculated(
            new_id(), application_id,
            score=outcome.total_score, tier=outcome.risk_tier, signal_count=len(signals)))
        await session.commit()
        try:
            await publish_pending(session)
        except Exception as exc:  # noqa: BLE001
            log.warning("events.relay_failed", error=str(exc))
        log.info(
            "risk.assessed",
            application_id=application_id,
            score=outcome.total_score,
            tier=outcome.risk_tier,
        )
        return {
            "status": "assessed",
            "application_id": application_id,
            "score": outcome.total_score,
            "tier": outcome.risk_tier,
        }


@celery_app.task(name="app.tasks.fraud.run_fraud_engine", bind=True, max_retries=3, default_retry_delay=10)
def run_fraud_engine(self, document_id: str) -> dict:
    try:
        return asyncio.run(run_fraud_engine_async(document_id))
    except Exception as exc:  # pragma: no cover - retry path needs a live broker
        raise self.retry(exc=exc) from exc


@celery_app.task(name="app.tasks.fraud.compute_risk_assessment", bind=True, max_retries=3, default_retry_delay=10)
def compute_risk_assessment(self, application_id: str) -> dict:
    try:
        return asyncio.run(compute_risk_assessment_async(application_id))
    except Exception as exc:  # pragma: no cover - retry path needs a live broker
        raise self.retry(exc=exc) from exc
