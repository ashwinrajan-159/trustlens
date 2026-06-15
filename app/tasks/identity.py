"""``run_identity_resolution`` — application-level identity intelligence (Phase 4).

Consolidates the identity values extracted across ALL of an application's documents into
one resolved ``IdentityProfile`` and emits IDENTITY-scope ``FraudSignal`` rows when core
attributes conflict (synthetic/stitched identity). Idempotent: prior IDENTITY signals and
the prior profile for the application are superseded on each run. Chains the risk recompute.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.encryption import mask_aadhaar, mask_pan
from app.core.logging import get_logger
from app.database import SessionFactory
from app.models.base import _utcnow
from app.models.enums import EntityType, FraudSignalType, SignalScope, SignalSeverity
from app.models.extracted_entity import ExtractedEntity
from app.models.fraud_signal import FraudSignal
from app.models.identity_profile import IdentityProfile
from app.services import identity as identity_service
from app.worker import celery_app

log = get_logger(__name__)
ENGINE_VERSION = "1.0.0"


async def run_identity_resolution_async(application_id: str, *, session_factory=None) -> dict:
    sf = session_factory or SessionFactory
    async with sf() as session:
        rows = (
            await session.execute(
                select(ExtractedEntity).where(
                    ExtractedEntity.application_id == application_id,
                    ExtractedEntity.deleted_at.is_(None),
                )
            )
        ).scalars().all()

        names, pans, aadhaars, dobs = [], [], [], []
        for e in rows:
            if e.value is None:
                continue
            if e.entity_type == EntityType.NAME:
                names.append(e.value)
            elif e.entity_type == EntityType.PAN:
                pans.append(e.value)
            elif e.entity_type == EntityType.AADHAAR:
                aadhaars.append(e.value)
            elif e.entity_type == EntityType.DOB:
                dobs.append(e.value)

        resolved, signals = identity_service.resolve(names, pans, aadhaars, dobs)

        # Idempotent: retire prior IDENTITY-scope signals + prior profile for this app.
        prior_signals = (
            await session.execute(
                select(FraudSignal).where(
                    FraudSignal.application_id == application_id,
                    FraudSignal.signal_scope == SignalScope.IDENTITY,
                    FraudSignal.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        for p in prior_signals:
            p.deleted_at = _utcnow()

        prior_profiles = (
            await session.execute(
                select(IdentityProfile).where(
                    IdentityProfile.application_id == application_id,
                    IdentityProfile.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        for p in prior_profiles:
            p.deleted_at = _utcnow()

        for r in signals:
            session.add(
                FraudSignal(
                    application_id=application_id,
                    document_id=None,
                    signal_type=FraudSignalType(r.signal_type),
                    severity=SignalSeverity(r.severity),
                    signal_scope=SignalScope.IDENTITY,
                    description=r.description,
                    evidence=r.evidence,
                    confidence=r.confidence,
                    rule_name=r.rule_name,
                    engine_version=ENGINE_VERSION,
                )
            )

        session.add(
            IdentityProfile(
                application_id=application_id,
                resolved_name=resolved.name,
                resolved_name_masked=identity_service.mask_name(resolved.name),
                pan=resolved.pan,
                pan_masked=mask_pan(resolved.pan) if resolved.pan else None,
                aadhaar_masked=(
                    mask_aadhaar(resolved.aadhaar_last4) if resolved.aadhaar_last4 else None
                ),
                dob=resolved.dob,
                distinct_name_count=resolved.distinct_name_count,
                distinct_pan_count=resolved.distinct_pan_count,
                distinct_dob_count=resolved.distinct_dob_count,
                synthetic_score=resolved.synthetic_score,
                is_synthetic_suspected=resolved.is_synthetic_suspected,
                indicators=resolved.indicators,
            )
        )
        await session.commit()
        log.info(
            "identity.resolved",
            application_id=application_id,
            synthetic=resolved.is_synthetic_suspected,
            identity_signals=len(signals),
        )

    # Chain the risk recompute so identity signals are reflected in the score.
    try:
        from app.tasks.fraud import compute_risk_assessment_async

        await compute_risk_assessment_async(application_id, session_factory=sf)
    except Exception as exc:  # noqa: BLE001
        log.error("identity.risk_chain_failed", application_id=application_id, error=str(exc))
    return {
        "status": "resolved",
        "application_id": application_id,
        "synthetic_suspected": resolved.is_synthetic_suspected,
    }


@celery_app.task(name="app.tasks.identity.run_identity_resolution", bind=True, max_retries=3, default_retry_delay=10)
def run_identity_resolution(self, application_id: str) -> dict:
    try:
        return asyncio.run(run_identity_resolution_async(application_id))
    except Exception as exc:  # pragma: no cover - retry path needs a live broker
        raise self.retry(exc=exc) from exc
