"""Closed-loop learning tasks (Phase 12).

When a senior reviewer records a CONFIRMED_FRAUD / FALSE_POSITIVE decision, the alert's
firing signals are folded into the fraud knowledge base: matched to (or used to create) a
pattern, recorded as an **immutable** ``pattern_case_link``, and the affected projections
(pattern counters + per-signal precision) are recomputed.

Idempotency is structural: the ``(pattern_id, alert_id)`` uniqueness means re-running this
task for the same review — a Celery redelivery, an outbox replay — never double-counts. A
nightly ``recompute_knowledge_base`` rebuilds every projection from the immutable record as a
drift backstop.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.logging import get_logger
from app.database import SessionFactory
from app.fraud_engine.scorer import SIGNAL_CATEGORY
from app.models.enums import ReviewDecision
from app.models.fraud_alert import FraudAlert
from app.models.fraud_signal import FraudSignal
from app.services.fraud_pattern import FraudPatternService
from app.services.signal_analytics import SignalAnalyticsService
from app.worker import celery_app

log = get_logger(__name__)

_LEARNING_OUTCOMES = {ReviewDecision.CONFIRMED_FRAUD, ReviewDecision.FALSE_POSITIVE}


def _dominant_category(signal_types: list[str]) -> str:
    """Explainable pattern category = the most common risk category among firing signals."""
    counts: dict[str, int] = {}
    for st in signal_types:
        cat = SIGNAL_CATEGORY.get(st, "DOCUMENT")
        counts[cat] = counts.get(cat, 0) + 1
    return max(counts, key=counts.get) if counts else "DOCUMENT"


async def learn_from_review_async(
    alert_id: str, application_id: str, decision: str, *, session_factory=None
) -> dict:
    try:
        outcome = ReviewDecision(decision)
    except ValueError:
        return {"status": "ignored", "reason": "unknown_decision", "decision": decision}
    if outcome not in _LEARNING_OUTCOMES:
        return {"status": "ignored", "reason": "non_learning_outcome", "decision": decision}

    sf = session_factory or SessionFactory
    async with sf() as session:
        alert = (
            await session.execute(select(FraudAlert).where(FraudAlert.id == alert_id))
        ).scalar_one_or_none()
        if alert is None:
            return {"status": "missing", "alert_id": alert_id}

        signals = (
            await session.execute(
                select(FraudSignal).where(
                    FraudSignal.application_id == application_id,
                    FraudSignal.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        signal_names = sorted({s.signal_type.value for s in signals})
        if not signal_names:
            return {"status": "skipped", "reason": "no_signals", "alert_id": alert_id}

        category = _dominant_category(signal_names)
        patterns = FraudPatternService(session)
        pattern = await patterns.match_or_create(category=category, signal_names=signal_names)
        created_link = await patterns.link_case(
            pattern_id=pattern.id, alert_id=alert_id, application_id=application_id,
            outcome=outcome, signal_names=signal_names,
        )
        await session.commit()
        # Recompute the touched pattern + global signal analytics (projections).
        await patterns.recompute(pattern.id)
        await SignalAnalyticsService(session).recompute_all()

    log.info(
        "learning.applied", alert_id=alert_id, pattern_id=pattern.id,
        outcome=outcome.value, new_link=created_link,
    )
    return {
        "status": "applied", "alert_id": alert_id, "pattern_id": pattern.id,
        "outcome": outcome.value, "new_link": created_link, "signal_count": len(signal_names),
    }


async def recompute_knowledge_base_async(*, session_factory=None) -> dict:
    """Drift backstop: rebuild every pattern's counters + all signal precision from the
    immutable record. Safe to run on a schedule."""
    sf = session_factory or SessionFactory
    async with sf() as session:
        patterns = FraudPatternService(session)
        all_patterns = await patterns.list_patterns()
        for p in all_patterns:
            await patterns.recompute(p.id)
        result = await SignalAnalyticsService(session).recompute_all()
    log.info("learning.recomputed_kb", patterns=len(all_patterns), signals=result.get("signals"))
    return {"status": "recomputed", "patterns": len(all_patterns), **result}


@celery_app.task(name="app.tasks.learning.learn_from_review", bind=True, max_retries=3, default_retry_delay=15)
def learn_from_review(self, alert_id: str, application_id: str, decision: str) -> dict:
    try:
        return asyncio.run(learn_from_review_async(alert_id, application_id, decision))
    except Exception as exc:  # pragma: no cover - retry path needs a live broker
        raise self.retry(exc=exc) from exc


@celery_app.task(name="app.tasks.learning.recompute_knowledge_base", bind=True, max_retries=2, default_retry_delay=30)
def recompute_knowledge_base(self) -> dict:
    try:
        return asyncio.run(recompute_knowledge_base_async())
    except Exception as exc:  # pragma: no cover - needs broker
        raise self.retry(exc=exc) from exc
