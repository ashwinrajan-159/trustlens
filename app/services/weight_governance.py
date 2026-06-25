"""Governed signal-weight tuning (Phase 12).

The deterministic risk engine's per-signal weights are data-driven and **governed**: a draft
is proposed, an ADMIN who is *not* the proposer approves & activates it, and the previously
active set is retired. Exactly one config is ACTIVE at a time; prior versions are retained so
every historical risk score stays reproducible (the version is stamped on each assessment).

Segregation of duties (proposer ≠ approver) and an append-only version history make weight
changes auditable — no silent, unattributed tuning of how fraud risk is scored.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.enums import AuditAction, WeightConfigStatus
from app.models.fraudops import SignalWeightConfig
from app.services.audit import AuditService

log = get_logger(__name__)


class WeightGovernanceService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.audit = AuditService(session)

    async def propose(
        self, *, weights: dict[str, float], rationale: str, proposed_by: str
    ) -> SignalWeightConfig:
        """Create a PROPOSED weight set (next version). Anyone with analyst+ may propose;
        activation is gated separately to a different ADMIN (SoD)."""
        if not weights:
            raise ValidationError("A weight set must contain at least one signal weight")
        for k, v in weights.items():
            if not isinstance(v, (int, float)) or v < 0:
                raise ValidationError(f"Weight for {k} must be a non-negative number")

        next_version = (
            (await self.session.execute(select(func.max(SignalWeightConfig.version)))).scalar() or 0
        ) + 1
        config = SignalWeightConfig(
            version=next_version, weights={k: float(v) for k, v in weights.items()},
            status=WeightConfigStatus.PROPOSED, rationale=rationale, created_by=proposed_by,
        )
        self.session.add(config)
        await self.session.flush()
        await self.audit.record(
            action=AuditAction.WEIGHT_PROPOSE, entity_type="signal_weight_config",
            entity_id=config.id, actor_id=proposed_by,
            after={"version": next_version, "weights": config.weights},
        )
        await self.session.commit()
        log.info("weights.proposed", version=next_version, by=proposed_by)
        return config

    async def approve_and_activate(self, config_id: str, *, approver_id: str) -> SignalWeightConfig:
        """Activate a proposed config (ADMIN, RBAC-checked at the API). SoD: the approver
        cannot be the proposer. Retires the currently-active config atomically."""
        config = (
            await self.session.execute(select(SignalWeightConfig).where(SignalWeightConfig.id == config_id))
        ).scalar_one_or_none()
        if not config:
            raise NotFoundError("Weight config not found")
        if config.status != WeightConfigStatus.PROPOSED:
            raise ConflictError(f"Only PROPOSED configs can be activated (is {config.status.value})")
        if config.created_by == approver_id:
            raise AuthorizationError("Segregation of duties: the proposer cannot approve their own weights")

        # Retire whatever is active now.
        for active in (
            await self.session.execute(
                select(SignalWeightConfig).where(SignalWeightConfig.status == WeightConfigStatus.ACTIVE)
            )
        ).scalars().all():
            active.status = WeightConfigStatus.RETIRED

        config.status = WeightConfigStatus.ACTIVE
        config.approved_by = approver_id
        config.activated_at = datetime.now(timezone.utc)
        await self.audit.record(
            action=AuditAction.WEIGHT_APPROVE, entity_type="signal_weight_config",
            entity_id=config.id, actor_id=approver_id,
            after={"version": config.version, "status": "ACTIVE"},
        )
        await self.session.commit()
        log.info("weights.activated", version=config.version, by=approver_id)
        return config

    async def active(self) -> SignalWeightConfig | None:
        return (
            await self.session.execute(
                select(SignalWeightConfig).where(SignalWeightConfig.status == WeightConfigStatus.ACTIVE)
            )
        ).scalar_one_or_none()

    async def active_overlay(self) -> tuple[dict[str, float] | None, int | None]:
        """Return ``(weights, version)`` for the active config, or ``(None, None)`` if none —
        the shape the scorer's ``weight_overlay`` expects."""
        cfg = await self.active()
        return (dict(cfg.weights), cfg.version) if cfg else (None, None)

    async def list_versions(self) -> list[SignalWeightConfig]:
        rows = (
            await self.session.execute(
                select(SignalWeightConfig).order_by(SignalWeightConfig.version.desc())
            )
        ).scalars().all()
        return list(rows)
