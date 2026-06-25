"""Alerting service + real-time escalation hook (Phase 10).

Creates SLA-tracked fraud alerts (idempotent: one open alert per application+type),
deriving the RBI reporting requirement + deadline from the loan exposure. The Phase 8
real-time engine's ``EscalationHook`` is wired here so a CRITICAL/HIGH ``RISK_CALCULATED``
or ``FRAUD_RING_DETECTED`` event becomes an alert sub-second. The hook resolves its DB
session from an injectable factory (overridable in tests).
"""
from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.security import new_id
from app.events import schemas as ev
from app.events.schemas import EventEnvelope
from app.events.service import publish_pending, stage
from app.models.application import Application
from app.models.enums import (
    ALERT_SLA_HOURS,
    AlertStatus,
    AlertType,
    EventType,
    SignalSeverity,
)
from app.models.fraud_alert import FraudAlert
from app.services import rbi

log = get_logger(__name__)

_OPEN_STATES = {AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED, AlertStatus.ESCALATED}


def _alert_number() -> str:
    ts = datetime.now(UTC).strftime("%Y%m%d")
    return f"AL-{ts}-{secrets.token_hex(4).upper()}"


class AlertingService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_for_application(
        self, application_id: str, *, alert_type: AlertType, severity: SignalSeverity, description: str
    ) -> FraudAlert:
        # Idempotent: reuse an existing open alert of the same type for this application.
        existing = (
            await self.session.execute(
                select(FraudAlert).where(
                    FraudAlert.application_id == application_id,
                    FraudAlert.alert_type == alert_type,
                    FraudAlert.status.in_(_OPEN_STATES),
                    FraudAlert.deleted_at.is_(None),
                )
            )
        ).scalars().first()
        if existing:
            return existing

        app = (
            await self.session.execute(select(Application).where(Application.id == application_id))
        ).scalar_one_or_none()
        amount = float(app.loan_amount_requested) if app else 0.0
        cls = rbi.classify(amount)

        now = datetime.now(UTC)
        sla_deadline = now + timedelta(hours=ALERT_SLA_HOURS.get(severity, 168))
        rbi_deadline = now + timedelta(hours=cls.deadline_hours) if cls.deadline_hours else None
        if rbi_deadline and rbi_deadline < sla_deadline:
            sla_deadline = rbi_deadline  # tighter regulatory clock wins

        alert = FraudAlert(
            alert_number=_alert_number(),
            application_id=application_id,
            alert_type=alert_type,
            severity=severity,
            status=AlertStatus.OPEN,
            description=description,
            rbi_reporting_required=cls.required,
            rbi_report_type=cls.report_type,
            rbi_deadline=rbi_deadline,
            sla_deadline=sla_deadline,
        )
        self.session.add(alert)
        await self.session.flush()
        stage(self.session, ev.fraud_alert_generated(
            new_id(), alert.id, application_id=application_id,
            alert_type=alert_type.value, severity=severity.value))
        await self.session.commit()
        try:
            await publish_pending(self.session)
        except Exception as exc:  # noqa: BLE001
            log.warning("events.relay_failed", error=str(exc))
        log.info("alert.created", alert_number=alert.alert_number, type=alert_type.value,
                 rbi=cls.report_type.value)
        return alert

    async def escalate_from_event(self, envelope: EventEnvelope) -> FraudAlert | None:
        """Map a high-severity domain event to an alert."""
        if envelope.event_type == EventType.RISK_CALCULATED:
            tier = (envelope.payload or {}).get("tier")
            if tier not in {"HIGH", "CRITICAL"}:
                return None
            return await self.create_for_application(
                envelope.aggregate_id,
                alert_type=AlertType.HIGH_RISK_APPLICATION,
                severity=SignalSeverity(tier),
                description=f"Application scored {tier} risk by the deterministic engine",
            )
        if envelope.event_type == EventType.FRAUD_RING_DETECTED:
            ring = (envelope.payload or {}).get("ring_size", 0)
            return await self.create_for_application(
                envelope.aggregate_id,
                alert_type=AlertType.FRAUD_RING,
                severity=SignalSeverity.CRITICAL,
                description=f"Application is part of a fraud ring of {ring} applications",
            )
        return None

    async def acknowledge(self, alert_id: str, *, by: str) -> FraudAlert:
        alert = await self._get(alert_id)
        alert.status = AlertStatus.ACKNOWLEDGED
        await self.session.commit()
        return alert

    async def claim(self, alert_id: str, *, by: str) -> FraudAlert:
        """Atomically claim an alert for investigation (Phase 12). Concurrency-safe:
        a conditional UPDATE on ``claimed_by IS NULL`` ensures only one analyst wins."""
        from datetime import datetime, timezone

        from sqlalchemy import update

        from app.models.enums import ApplicationStatus, AuditAction
        from app.services.audit import AuditService

        result = await self.session.execute(
            update(FraudAlert)
            .where(FraudAlert.id == alert_id, FraudAlert.claimed_by.is_(None))
            .values(claimed_by=by, claimed_at=datetime.now(timezone.utc), status=AlertStatus.INVESTIGATING)
        )
        if result.rowcount == 0:
            alert = await self._get(alert_id)  # 404 if missing
            from app.core.exceptions import ConflictError

            raise ConflictError(f"Alert already claimed by {alert.claimed_by}")
        alert = await self._get(alert_id)

        # Move the application into investigation (best-effort, guarded transition).
        await self._advance_application(alert.application_id, ApplicationStatus.UNDER_INVESTIGATION)
        await AuditService(self.session).record(
            action=AuditAction.CLAIM, entity_type="alert", entity_id=alert_id,
            actor_id=by, after={"status": alert.status.value, "claimed_by": by},
        )
        await self.session.commit()
        return alert

    async def transition(self, alert_id: str, target: AlertStatus, *, by: str, reason: str | None = None) -> FraudAlert:
        """Guarded alert state transition. Illegal transitions raise; reopening a
        RESOLVED/DISMISSED alert requires an explicit reason."""
        from app.core.exceptions import StateTransitionError
        from app.models.enums import ALERT_TRANSITIONS, AuditAction
        from app.services.audit import AuditService

        alert = await self._get(alert_id)
        allowed = ALERT_TRANSITIONS.get(alert.status, set())
        if target not in allowed:
            if alert.status in {AlertStatus.RESOLVED, AlertStatus.DISMISSED} and reason:
                pass  # explicit guarded reopen
            else:
                raise StateTransitionError(f"Cannot move alert {alert.status.value} → {target.value}")
        before = alert.status.value
        alert.status = target
        await AuditService(self.session).record(
            action=AuditAction.STATE_TRANSITION, entity_type="alert", entity_id=alert_id,
            actor_id=by, before={"status": before}, after={"status": target.value, "reason": reason},
        )
        await self.session.commit()
        return alert

    async def _advance_application(self, application_id: str, target) -> None:
        from app.models.application import Application
        from app.models.enums import APPLICATION_TRANSITIONS

        app = (
            await self.session.execute(select(Application).where(Application.id == application_id))
        ).scalar_one_or_none()
        if app and target in APPLICATION_TRANSITIONS.get(app.status, set()):
            app.status = target

    async def resolve(self, alert_id: str, *, by: str, dismiss: bool = False) -> FraudAlert:
        alert = await self._get(alert_id)
        alert.status = AlertStatus.DISMISSED if dismiss else AlertStatus.RESOLVED
        alert.resolved_at = datetime.now(UTC)
        alert.resolved_by = by
        await self.session.commit()
        return alert

    async def _get(self, alert_id: str) -> FraudAlert:
        from app.core.exceptions import NotFoundError

        alert = (
            await self.session.execute(select(FraudAlert).where(FraudAlert.id == alert_id))
        ).scalar_one_or_none()
        if not alert:
            raise NotFoundError("Alert not found")
        return alert

    async def mark_sla_breaches(self) -> int:
        """Flag open alerts past their SLA deadline (ops sweep). Returns count flagged."""
        now = datetime.now(UTC)
        rows = (
            await self.session.execute(
                select(FraudAlert).where(
                    FraudAlert.status.in_(_OPEN_STATES),
                    FraudAlert.sla_breached.is_(False),
                    FraudAlert.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        n = 0
        for a in rows:
            if a.sla_deadline and a.sla_deadline < now:
                a.sla_breached = True
                n += 1
        await self.session.commit()
        return n


# ── Real-time escalation hook (wired into the Phase 8 consumer) ──

_hook_session_factory = None


def set_hook_session_factory(factory) -> None:
    global _hook_session_factory
    _hook_session_factory = factory


async def escalation_hook(envelope: EventEnvelope) -> None:
    """Called by the real-time engine; creates an alert in its own session."""
    from app.database import SessionFactory

    factory = _hook_session_factory or SessionFactory
    try:
        async with factory() as session:
            await AlertingService(session).escalate_from_event(envelope)
    except Exception as exc:  # noqa: BLE001 - never let escalation break the bus
        log.error("alert.escalation_failed", event_id=envelope.event_id, error=str(exc))


def install_escalation_hook() -> None:
    """Register the alert-creating escalation hook on the real-time engine."""
    from app.events import consumer

    consumer.EscalationHook = escalation_hook
