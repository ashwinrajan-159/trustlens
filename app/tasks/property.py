"""``run_property_validation`` — collateral intelligence (Phase 6).

Consolidates property attributes for an application and runs the pure property service,
including a cross-application **duplicate-collateral** check: the same survey number
pledged on a different application is a strong fraud signal. Survey numbers are stored
encrypted at rest (ExtractedEntity uses EncryptedString with non-deterministic ciphertext),
so the cross-app match is done in Python on decrypted values, not via a SQL IN clause.
Idempotent; chains financial validation.
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
from app.models.identity_profile import IdentityProfile
from app.models.property_profile import PropertyProfile
from app.services import property_intel
from app.worker import celery_app

log = get_logger(__name__)
ENGINE_VERSION = "1.0.0"


def _floats(values: list[str]) -> list[float]:
    out = []
    for v in values:
        try:
            out.append(float(str(v).replace(",", "")))
        except (TypeError, ValueError):
            continue
    return out


async def run_property_validation_async(application_id: str, *, session_factory=None) -> dict:
    sf = session_factory or SessionFactory
    async with sf() as session:
        mine = (
            await session.execute(
                select(ExtractedEntity).where(
                    ExtractedEntity.application_id == application_id,
                    ExtractedEntity.deleted_at.is_(None),
                )
            )
        ).scalars().all()

        def vals(t: EntityType) -> list[str]:
            return [e.value for e in mine if e.entity_type == t and e.value]

        surveys = vals(EntityType.SURVEY_NUMBER)
        my_survey_set = {s.strip().upper() for s in surveys}

        # Cross-application duplicate collateral (compare decrypted values in Python).
        dup_app_ids: list[str] = []
        if my_survey_set:
            others = (
                await session.execute(
                    select(ExtractedEntity).where(
                        ExtractedEntity.entity_type == EntityType.SURVEY_NUMBER,
                        ExtractedEntity.application_id != application_id,
                        ExtractedEntity.deleted_at.is_(None),
                    )
                )
            ).scalars().all()
            dup = {
                e.application_id
                for e in others
                if e.value and e.value.strip().upper() in my_survey_set
            }
            dup_app_ids = sorted(dup)

        # Applicant name: prefer the resolved identity, else any NAME entity.
        profile = (
            await session.execute(
                select(IdentityProfile).where(
                    IdentityProfile.application_id == application_id,
                    IdentityProfile.deleted_at.is_(None),
                )
            )
        ).scalars().first()
        applicant_name = profile.resolved_name if profile and profile.resolved_name else (
            vals(EntityType.NAME)[0] if vals(EntityType.NAME) else None
        )

        ctx = property_intel.PropertyContext(
            survey_numbers=surveys,
            areas=_floats(vals(EntityType.PROPERTY_AREA)),
            sale_considerations=_floats(vals(EntityType.SALE_CONSIDERATION)),
            valuations=_floats(vals(EntityType.VALUATION_AMOUNT)),
            owner_names=vals(EntityType.OWNER_NAME),
            applicant_name=applicant_name,
            duplicate_collateral_app_ids=dup_app_ids,
        )
        signals, summary = property_intel.validate(ctx)

        # Idempotent: retire prior PROPERTY signals + profile.
        for p in (
            await session.execute(
                select(FraudSignal).where(
                    FraudSignal.application_id == application_id,
                    FraudSignal.signal_scope == SignalScope.PROPERTY,
                    FraudSignal.deleted_at.is_(None),
                )
            )
        ).scalars().all():
            p.deleted_at = _utcnow()
        for p in (
            await session.execute(
                select(PropertyProfile).where(
                    PropertyProfile.application_id == application_id,
                    PropertyProfile.deleted_at.is_(None),
                )
            )
        ).scalars().all():
            p.deleted_at = _utcnow()

        for r in signals:
            session.add(
                FraudSignal(
                    application_id=application_id, document_id=None,
                    signal_type=FraudSignalType(r.signal_type),
                    severity=SignalSeverity(r.severity), signal_scope=SignalScope.PROPERTY,
                    description=r.description, evidence=r.evidence, confidence=r.confidence,
                    rule_name=r.rule_name, engine_version=ENGINE_VERSION,
                )
            )
        # Only persist a profile if there is any property data.
        if any([summary.survey_numbers, summary.area, summary.sale_consideration, summary.valuation]):
            session.add(
                PropertyProfile(
                    application_id=application_id,
                    survey_numbers=summary.survey_numbers,
                    area=summary.area,
                    sale_consideration=summary.sale_consideration,
                    valuation=summary.valuation,
                    valuation_ratio=summary.valuation_ratio,
                    is_inflated=summary.is_inflated,
                    duplicate_collateral_app_ids=summary.duplicate_collateral_app_ids,
                )
            )
        await session.commit()
        log.info("property.validated", application_id=application_id, signals=len(signals))

    try:
        from app.tasks.financial import run_financial_validation_async

        await run_financial_validation_async(application_id, session_factory=sf)
    except Exception as exc:  # noqa: BLE001
        log.error("property.financial_chain_failed", application_id=application_id, error=str(exc))
    return {"status": "validated", "application_id": application_id, "signals": len(signals)}


@celery_app.task(name="app.tasks.property.run_property_validation", bind=True, max_retries=3, default_retry_delay=10)
def run_property_validation(self, application_id: str) -> dict:
    try:
        return asyncio.run(run_property_validation_async(application_id))
    except Exception as exc:  # pragma: no cover - retry path needs a live broker
        raise self.retry(exc=exc) from exc
