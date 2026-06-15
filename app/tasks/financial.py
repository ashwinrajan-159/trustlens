"""``run_financial_validation`` — business/financial intelligence (Phase 6).

Separates revenue figures by source document (ITR vs GST return) via a join on the
document type, runs the pure financial service, persists FINANCIAL signals + a
BusinessProfile. Idempotent; chains the risk recompute (last step of the pipeline).
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.logging import get_logger
from app.database import SessionFactory
from app.models.base import _utcnow
from app.models.business_profile import BusinessProfile
from app.models.document import Document
from app.models.enums import DocumentType, EntityType, FraudSignalType, SignalScope, SignalSeverity
from app.models.extracted_entity import ExtractedEntity
from app.models.fraud_signal import FraudSignal
from app.services import financial as financial_service
from app.worker import celery_app

log = get_logger(__name__)
ENGINE_VERSION = "1.0.0"


def _f(v: str) -> float | None:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


async def run_financial_validation_async(application_id: str, *, session_factory=None) -> dict:
    sf = session_factory or SessionFactory
    async with sf() as session:
        # Entities joined with their document's type, so REVENUE can be split ITR vs GST.
        rows = (
            await session.execute(
                select(ExtractedEntity, Document.document_type)
                .join(Document, ExtractedEntity.document_id == Document.id)
                .where(
                    ExtractedEntity.application_id == application_id,
                    ExtractedEntity.deleted_at.is_(None),
                )
            )
        ).all()

        itr_rev, gst_rev, net_profits = [], [], []
        for entity, doc_type in rows:
            if entity.value is None:
                continue
            val = _f(entity.value)
            if val is None:
                continue
            if entity.entity_type == EntityType.REVENUE:
                if doc_type == DocumentType.ITR:
                    itr_rev.append(val)
                elif doc_type == DocumentType.GST_RETURN:
                    gst_rev.append(val)
            elif entity.entity_type == EntityType.NET_PROFIT:
                net_profits.append(val)

        ctx = financial_service.FinancialContext(
            itr_revenues=itr_rev, gst_revenues=gst_rev, net_profits=net_profits
        )
        signals, summary = financial_service.validate(ctx)

        # Idempotent: retire prior FINANCIAL signals + profile.
        for p in (
            await session.execute(
                select(FraudSignal).where(
                    FraudSignal.application_id == application_id,
                    FraudSignal.signal_scope == SignalScope.FINANCIAL,
                    FraudSignal.deleted_at.is_(None),
                )
            )
        ).scalars().all():
            p.deleted_at = _utcnow()
        for p in (
            await session.execute(
                select(BusinessProfile).where(
                    BusinessProfile.application_id == application_id,
                    BusinessProfile.deleted_at.is_(None),
                )
            )
        ).scalars().all():
            p.deleted_at = _utcnow()

        for r in signals:
            session.add(
                FraudSignal(
                    application_id=application_id, document_id=None,
                    signal_type=FraudSignalType(r.signal_type),
                    severity=SignalSeverity(r.severity), signal_scope=SignalScope.FINANCIAL,
                    description=r.description, evidence=r.evidence, confidence=r.confidence,
                    rule_name=r.rule_name, engine_version=ENGINE_VERSION,
                )
            )
        if any([summary.itr_revenue, summary.gst_revenue, summary.net_profit]):
            session.add(
                BusinessProfile(
                    application_id=application_id,
                    itr_revenue=summary.itr_revenue,
                    gst_revenue=summary.gst_revenue,
                    net_profit=summary.net_profit,
                    revenue_gap_ratio=summary.revenue_gap_ratio,
                )
            )
        await session.commit()
        log.info("financial.validated", application_id=application_id, signals=len(signals))

    # Chain graph analysis (Phase 7), which recomputes the risk score (final step).
    try:
        from app.tasks.graph import run_graph_analysis_async

        await run_graph_analysis_async(application_id, session_factory=sf)
    except Exception as exc:  # noqa: BLE001
        log.error("financial.graph_chain_failed", application_id=application_id, error=str(exc))
    return {"status": "validated", "application_id": application_id, "signals": len(signals)}


@celery_app.task(name="app.tasks.financial.run_financial_validation", bind=True, max_retries=3, default_retry_delay=10)
def run_financial_validation(self, application_id: str) -> dict:
    try:
        return asyncio.run(run_financial_validation_async(application_id))
    except Exception as exc:  # pragma: no cover - retry path needs a live broker
        raise self.retry(exc=exc) from exc
