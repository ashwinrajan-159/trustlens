"""Fraud knowledge base (Phase 12).

Confirmed/false-positive reviews link to a fraud *pattern* via immutable
``pattern_case_links``. Matching is deterministic and explainable — by category +
Jaccard similarity of the firing signal-set over a threshold — not opaque clustering, so
near-duplicate patterns are prevented and an admin can merge if needed. Pattern counters
(`occurrences/confirmed/FP/confidence`) are **projections recomputed from the links**, never
mutated in place, so they can be rebuilt exactly and never silently drift.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.models.enums import ReviewDecision, SignalSeverity
from app.models.fraudops import FraudPattern, PatternCaseLink

log = get_logger(__name__)

# Two signal-sets in the same category are "the same pattern" at/above this Jaccard
# similarity. 0.6 balances dedup vs. over-merging distinct fraud shapes (tunable).
PATTERN_SIMILARITY_THRESHOLD = 0.6


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


class FraudPatternService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def match_or_create(
        self, *, category: str, signal_names: list[str], severity: SignalSeverity = SignalSeverity.MEDIUM
    ) -> FraudPattern:
        """Find the best-matching existing pattern in this category by signal-set
        similarity, else create a new one with an explainable detection_logic."""
        sigset = set(signal_names)
        candidates = (
            await self.session.execute(
                select(FraudPattern).where(
                    FraudPattern.category == category, FraudPattern.deleted_at.is_(None)
                )
            )
        ).scalars().all()

        best, best_sim = None, 0.0
        for p in candidates:
            existing = set((p.detection_logic or {}).get("signal_types", []))
            sim = _jaccard(sigset, existing)
            if sim > best_sim:
                best, best_sim = p, sim
        if best is not None and best_sim >= PATTERN_SIMILARITY_THRESHOLD:
            return best

        name = f"{category} pattern: {', '.join(sorted(sigset)[:3]) or 'unspecified'}"
        pattern = FraudPattern(
            name=name[:128], category=category,
            description=f"Auto-derived from confirmed cases firing {sorted(sigset)}",
            severity=severity,
            detection_logic={"category": category, "signal_types": sorted(sigset)},
        )
        self.session.add(pattern)
        await self.session.flush()
        log.info("pattern.created", pattern_id=pattern.id, category=category)
        return pattern

    async def link_case(
        self, *, pattern_id: str, alert_id: str, application_id: str,
        outcome: ReviewDecision, signal_names: list[str],
    ) -> bool:
        """Record immutable pattern↔case evidence. Idempotent on (pattern, alert):
        returns False if the link already exists (so learning never double-counts)."""
        exists = (
            await self.session.execute(
                select(PatternCaseLink).where(
                    PatternCaseLink.pattern_id == pattern_id, PatternCaseLink.alert_id == alert_id
                )
            )
        ).scalars().first()
        if exists:
            return False
        self.session.add(PatternCaseLink(
            pattern_id=pattern_id, alert_id=alert_id, application_id=application_id,
            outcome=outcome, signal_names=signal_names,
        ))
        await self.session.flush()
        return True

    async def recompute(self, pattern_id: str) -> FraudPattern:
        """Rebuild a pattern's counters from its immutable links (projection)."""
        pattern = (
            await self.session.execute(select(FraudPattern).where(FraudPattern.id == pattern_id))
        ).scalar_one_or_none()
        if not pattern:
            raise NotFoundError("Pattern not found")
        links = (
            await self.session.execute(
                select(PatternCaseLink).where(PatternCaseLink.pattern_id == pattern_id)
            )
        ).scalars().all()
        confirmed = sum(1 for x in links if x.outcome == ReviewDecision.CONFIRMED_FRAUD)
        fp = sum(1 for x in links if x.outcome == ReviewDecision.FALSE_POSITIVE)
        pattern.occurrences = len(links)
        pattern.confirmed_cases = confirmed
        pattern.false_positive_count = fp
        denom = confirmed + fp
        pattern.pattern_confidence = round(confirmed / denom, 4) if denom else 0.0
        await self.session.commit()
        return pattern

    async def merge(self, *, source_id: str, target_id: str) -> FraudPattern:
        """Admin merge of a near-duplicate pattern: re-point links, soft-delete source,
        recompute target. Idempotent on the (target, alert) uniqueness."""
        from app.models.base import _utcnow

        if source_id == target_id:
            raise ConflictError("Cannot merge a pattern into itself")
        source = (await self.session.execute(select(FraudPattern).where(FraudPattern.id == source_id))).scalar_one_or_none()
        target = (await self.session.execute(select(FraudPattern).where(FraudPattern.id == target_id))).scalar_one_or_none()
        if not source or not target:
            raise NotFoundError("Pattern not found")
        links = (await self.session.execute(select(PatternCaseLink).where(PatternCaseLink.pattern_id == source_id))).scalars().all()
        target_alerts = {
            x.alert_id for x in
            (await self.session.execute(select(PatternCaseLink).where(PatternCaseLink.pattern_id == target_id))).scalars().all()
        }
        for link in links:
            if link.alert_id in target_alerts:
                continue  # already represented in target (dedup)
            link.pattern_id = target_id
        source.deleted_at = _utcnow()
        await self.session.flush()
        return await self.recompute(target_id)

    async def list_patterns(self) -> list[FraudPattern]:
        rows = (
            await self.session.execute(
                select(FraudPattern)
                .where(FraudPattern.deleted_at.is_(None))
                .order_by(FraudPattern.pattern_confidence.desc(), FraudPattern.confirmed_cases.desc())
            )
        ).scalars().all()
        return list(rows)

    async def get(self, pattern_id: str) -> FraudPattern:
        p = (await self.session.execute(select(FraudPattern).where(FraudPattern.id == pattern_id))).scalar_one_or_none()
        if not p:
            raise NotFoundError("Pattern not found")
        return p
