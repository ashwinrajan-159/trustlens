"""``run_cross_document_validation`` — application-level cross-document checks (Phase 5).

Builds a summary of the application's PROCESSED documents (present types + income
figures) and runs the pure cross-document service: completeness checklist + salary↔bank
reconciliation. Naturally deferred — reconciliation only fires once both a salary slip and
a bank statement are processed. Idempotent: prior CROSS_DOCUMENT signals are superseded.
Chains the risk recompute.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.logging import get_logger
from app.database import SessionFactory
from app.models.base import _utcnow
from app.models.document import Document
from app.models.enums import (
    DocumentStatus,
    EntityType,
    FraudSignalType,
    SignalScope,
    SignalSeverity,
)
from app.models.extracted_entity import ExtractedEntity
from app.models.fraud_signal import FraudSignal
from app.services import cross_document as xdoc
from app.worker import celery_app

log = get_logger(__name__)
ENGINE_VERSION = "1.0.0"


def _to_floats(values: list[str]) -> list[float]:
    out = []
    for v in values:
        try:
            out.append(float(str(v).replace(",", "")))
        except (TypeError, ValueError):
            continue
    return out


async def run_cross_document_validation_async(application_id: str, *, session_factory=None) -> dict:
    sf = session_factory or SessionFactory
    async with sf() as session:
        from app.models.application import Application

        application = (
            await session.execute(select(Application).where(Application.id == application_id))
        ).scalar_one_or_none()
        if application is None:
            return {"status": "missing", "application_id": application_id}

        # Present document types = current, PROCESSED docs only (deferred until processed).
        processed_docs = (
            await session.execute(
                select(Document).where(
                    Document.application_id == application_id,
                    Document.deleted_at.is_(None),
                    Document.is_current_version.is_(True),
                    Document.status == DocumentStatus.PROCESSED,
                )
            )
        ).scalars().all()
        present_types = {d.document_type.value for d in processed_docs}

        entities = (
            await session.execute(
                select(ExtractedEntity).where(
                    ExtractedEntity.application_id == application_id,
                    ExtractedEntity.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        net_salaries = _to_floats([e.value for e in entities if e.entity_type == EntityType.NET_SALARY and e.value])
        salary_credits = _to_floats([e.value for e in entities if e.entity_type == EntityType.SALARY_CREDIT and e.value])

        ctx = xdoc.CrossDocContext(
            loan_type=application.loan_type.value,
            present_doc_types=present_types,
            net_salaries=net_salaries,
            salary_credits=salary_credits,
        )
        results = xdoc.validate(ctx)

        # Idempotent: retire prior CROSS_DOCUMENT signals for this application.
        prior = (
            await session.execute(
                select(FraudSignal).where(
                    FraudSignal.application_id == application_id,
                    FraudSignal.signal_scope == SignalScope.CROSS_DOCUMENT,
                    FraudSignal.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        for p in prior:
            p.deleted_at = _utcnow()

        for r in results:
            session.add(
                FraudSignal(
                    application_id=application_id,
                    document_id=None,
                    signal_type=FraudSignalType(r.signal_type),
                    severity=SignalSeverity(r.severity),
                    signal_scope=SignalScope.CROSS_DOCUMENT,
                    description=r.description,
                    evidence=r.evidence,
                    confidence=r.confidence,
                    rule_name=r.rule_name,
                    engine_version=ENGINE_VERSION,
                )
            )
        await session.commit()
        log.info("crossdoc.validated", application_id=application_id, signals=len(results))

    # Chain property validation (Phase 6) → financial → risk.
    try:
        from app.tasks.property import run_property_validation_async

        await run_property_validation_async(application_id, session_factory=sf)
    except Exception as exc:  # noqa: BLE001
        log.error("crossdoc.property_chain_failed", application_id=application_id, error=str(exc))
    return {"status": "validated", "application_id": application_id, "signals": len(results)}


@celery_app.task(name="app.tasks.cross_document.run_cross_document_validation", bind=True, max_retries=3, default_retry_delay=10)
def run_cross_document_validation(self, application_id: str) -> dict:
    try:
        return asyncio.run(run_cross_document_validation_async(application_id))
    except Exception as exc:  # pragma: no cover - retry path needs a live broker
        raise self.retry(exc=exc) from exc
