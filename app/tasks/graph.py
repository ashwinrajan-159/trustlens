"""``run_graph_analysis`` — network fraud detection (Phase 7), final analysis step.

Builds the entity-relationship graph from ALL applications' extracted attributes
(decrypted in Python — EncryptedString ciphertext is non-deterministic so it can't be
SQL-joined), analyses the target application's neighbourhood, persists a GraphAnalysis +
GRAPH-scope FraudSignals, then recomputes the risk score. Idempotent.

``load_records`` is shared with the read-only network endpoint.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.logging import get_logger
from app.database import SessionFactory
from app.models.base import _utcnow
from app.models.enums import EntityType, FraudSignalType, SignalScope, SignalSeverity
from app.models.extracted_entity import ExtractedEntity
from app.models.fraud_signal import FraudSignal
from app.models.graph_analysis import GraphAnalysis
from app.services import graph_intel
from app.services.identity import normalize_name
from app.worker import celery_app

log = get_logger(__name__)
ENGINE_VERSION = "1.0.0"

_KIND_FIELDS = {
    EntityType.NAME: "names",
    EntityType.PAN: "pans",
    EntityType.AADHAAR: "aadhaars",
    EntityType.ACCOUNT_NUMBER: "accounts",
    EntityType.SURVEY_NUMBER: "surveys",
    EntityType.GSTIN: "gstins",
}


async def load_records(session) -> list[graph_intel.AppRecord]:
    """Build one AppRecord per application from all live identity/collateral entities."""
    rows = (
        await session.execute(
            select(ExtractedEntity).where(
                ExtractedEntity.deleted_at.is_(None),
                ExtractedEntity.entity_type.in_(list(_KIND_FIELDS.keys())),
            )
        )
    ).scalars().all()

    by_app: dict[str, graph_intel.AppRecord] = {}
    for e in rows:
        if not e.value:
            continue
        rec = by_app.get(e.application_id)
        if rec is None:
            rec = graph_intel.AppRecord(application_id=e.application_id)
            by_app[e.application_id] = rec
        field = _KIND_FIELDS[e.entity_type]
        value = normalize_name(e.value) if e.entity_type == EntityType.NAME else e.value
        if value:
            getattr(rec, field).append(value)
    return list(by_app.values())


async def run_graph_analysis_async(application_id: str, *, session_factory=None) -> dict:
    sf = session_factory or SessionFactory
    async with sf() as session:
        records = await load_records(session)
        graph = graph_intel.build_graph(records)
        summary, signals = graph_intel.analyze(graph, application_id)

        # Idempotent: retire prior GRAPH signals + prior analysis.
        for p in (
            await session.execute(
                select(FraudSignal).where(
                    FraudSignal.application_id == application_id,
                    FraudSignal.signal_scope == SignalScope.GRAPH,
                    FraudSignal.deleted_at.is_(None),
                )
            )
        ).scalars().all():
            p.deleted_at = _utcnow()
        for p in (
            await session.execute(
                select(GraphAnalysis).where(
                    GraphAnalysis.application_id == application_id,
                    GraphAnalysis.deleted_at.is_(None),
                )
            )
        ).scalars().all():
            p.deleted_at = _utcnow()

        for r in signals:
            session.add(
                FraudSignal(
                    application_id=application_id, document_id=None,
                    signal_type=FraudSignalType(r.signal_type),
                    severity=SignalSeverity(r.severity), signal_scope=SignalScope.GRAPH,
                    description=r.description, evidence=r.evidence, confidence=r.confidence,
                    rule_name=r.rule_name, engine_version=ENGINE_VERSION,
                )
            )
        session.add(
            GraphAnalysis(
                application_id=application_id,
                graph_risk_score=summary.graph_risk_score,
                fraud_connections_count=summary.fraud_connections_count,
                shared_pan_count=summary.shared_pan_count,
                shared_account_count=summary.shared_account_count,
                shared_property_count=summary.shared_property_count,
                ring_size=summary.ring_size,
                in_fraud_ring=summary.in_fraud_ring,
                connected_application_ids=summary.connected_application_ids,
            )
        )
        await session.commit()
        log.info(
            "graph.analyzed",
            application_id=application_id,
            connections=summary.fraud_connections_count,
            ring=summary.in_fraud_ring,
            signals=len(signals),
        )

    try:
        from app.tasks.fraud import compute_risk_assessment_async

        await compute_risk_assessment_async(application_id, session_factory=sf)
    except Exception as exc:  # noqa: BLE001
        log.error("graph.risk_chain_failed", application_id=application_id, error=str(exc))
    return {"status": "analyzed", "application_id": application_id, "signals": len(signals)}


@celery_app.task(name="app.tasks.graph.run_graph_analysis", bind=True, max_retries=3, default_retry_delay=10)
def run_graph_analysis(self, application_id: str) -> dict:
    try:
        return asyncio.run(run_graph_analysis_async(application_id))
    except Exception as exc:  # pragma: no cover - retry path needs a live broker
        raise self.retry(exc=exc) from exc
