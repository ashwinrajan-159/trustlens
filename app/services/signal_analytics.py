"""Signal analytics (Phase 12) — per-signal precision under sample-size discipline.

Precision = confirmed / (confirmed + false_positive) for a signal, computed **only from the
immutable record** (confirmed firings from ``pattern_case_links``; FP firings from
``false_positive_records``), so the ``signal_performance`` table is a recomputable projection.

Two disciplines guard against feedback-loop bias (the decisions were influenced by the very
signals shown to the analyst):
- a **minimum sample size** before a precision number is flagged ``sample_sufficient`` (and
  thus actionable for weight recommendations); and
- a **Wilson score confidence interval** reported alongside the point estimate, never a bare
  percentage. All of this is advisory only — it never auto-changes weights.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import get_logger
from app.models.enums import ReviewDecision
from app.models.fraudops import FalsePositiveRecord, PatternCaseLink, SignalPerformance

log = get_logger(__name__)

_Z = 1.96  # 95% confidence


def wilson_interval(successes: int, n: int, z: float = _Z) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion — well-behaved at small n / extremes."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = (z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)) / denom
    return (round(max(0.0, centre - margin), 4), round(min(1.0, centre + margin), 4))


class SignalAnalyticsService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.min_sample = getattr(settings, "signal_min_sample", 10)

    async def recompute_all(self) -> dict:
        """Rebuild every ``signal_performance`` row from the immutable record (drift-proof)."""
        confirmed: dict[str, int] = {}
        for link in (
            await self.session.execute(
                select(PatternCaseLink).where(PatternCaseLink.outcome == ReviewDecision.CONFIRMED_FRAUD)
            )
        ).scalars().all():
            for s in link.signal_names or []:
                confirmed[s] = confirmed.get(s, 0) + 1

        fp: dict[str, int] = {}
        for rec in (
            await self.session.execute(
                select(FalsePositiveRecord).where(FalsePositiveRecord.deleted_at.is_(None))
            )
        ).scalars().all():
            for s in rec.signal_names or []:
                fp[s] = fp.get(s, 0) + 1

        existing = {
            r.signal_name: r
            for r in (await self.session.execute(select(SignalPerformance))).scalars().all()
        }
        now = datetime.now(timezone.utc)
        names = set(confirmed) | set(fp) | set(existing)
        for name in names:
            c, f = confirmed.get(name, 0), fp.get(name, 0)
            n = c + f
            precision = round(c / n, 4) if n else 0.0
            lo, hi = wilson_interval(c, n)
            row = existing.get(name) or SignalPerformance(signal_name=name)
            row.times_triggered = n
            row.confirmed_fraud_count = c
            row.false_positive_count = f
            row.precision_score = precision
            row.sample_sufficient = n >= self.min_sample
            row.precision_ci_low = lo
            row.precision_ci_high = hi
            row.last_updated = now
            self.session.add(row)
        await self.session.commit()
        log.info("signal_analytics.recomputed", signals=len(names))
        return {"signals": len(names)}

    async def table(self) -> list[SignalPerformance]:
        rows = (
            await self.session.execute(
                select(SignalPerformance).order_by(SignalPerformance.precision_score.desc())
            )
        ).scalars().all()
        return list(rows)
