"""Review service (Phase 12) — the human-final decision step, SoD-enforced.

A SENIOR_ANALYST who is **not** the investigator records a decision on an investigation
report. The decision drives the alert/application state machines, captures false positives
with a controlled reason code, hooks confirmed fraud into the existing RBI flow, and emits
``review.decision.recorded`` (existing outbox) to trigger async, idempotent learning.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.security import new_id
from app.events import schemas as ev
from app.events.service import publish_pending, stage
from app.models.application import Application
from app.models.enums import (
    APPLICATION_TRANSITIONS,
    AlertStatus,
    ApplicationStatus,
    AuditAction,
    FPReasonCode,
    ReviewDecision,
)
from app.models.fraud_alert import FraudAlert
from app.models.fraud_signal import FraudSignal
from app.models.fraudops import (
    FalsePositiveRecord,
    InvestigationReport,
    ReviewDecisionRecord,
)
from app.services.audit import AuditService

log = get_logger(__name__)


class ReviewService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.audit = AuditService(session)

    async def record_decision(
        self, report_id: str, *, reviewer_id: str, decision: ReviewDecision,
        comments: str = "", fp_reason_code: FPReasonCode | None = None,
    ) -> ReviewDecisionRecord:
        report = (
            await self.session.execute(select(InvestigationReport).where(InvestigationReport.id == report_id))
        ).scalar_one_or_none()
        if not report:
            raise NotFoundError("Investigation report not found")

        # Segregation of duties: the reviewer cannot be the investigator.
        if reviewer_id == report.underwriter_id:
            raise AuthorizationError("Segregation of duties: the investigator cannot review their own report")

        alert = (
            await self.session.execute(select(FraudAlert).where(FraudAlert.id == report.alert_id))
        ).scalar_one_or_none()
        if not alert:
            raise NotFoundError("Alert not found")
        if alert.status != AlertStatus.REVIEW_PENDING:
            raise ConflictError(f"Alert must be REVIEW_PENDING to review (is {alert.status.value})")
        if decision == ReviewDecision.FALSE_POSITIVE and fp_reason_code is None:
            raise ValidationError("A false-positive reason code is required")

        record = ReviewDecisionRecord(
            report_id=report_id, alert_id=alert.id, reviewer_id=reviewer_id,
            decision=decision, comments=comments, fp_reason_code=fp_reason_code,
        )
        self.session.add(record)
        await self.session.flush()

        app = (
            await self.session.execute(select(Application).where(Application.id == alert.application_id))
        ).scalar_one_or_none()

        def advance(target: ApplicationStatus) -> None:
            if app and target in APPLICATION_TRANSITIONS.get(app.status, set()):
                app.status = target

        emit = False
        if decision == ReviewDecision.CONFIRMED_FRAUD:
            advance(ApplicationStatus.CONFIRMED_FRAUD)
            alert.status = AlertStatus.RESOLVED
            alert.resolved_by = reviewer_id
            emit = True
        elif decision == ReviewDecision.FALSE_POSITIVE:
            await self._record_false_positive(alert, record, fp_reason_code, app)
            advance(ApplicationStatus.UNDER_REVIEW)  # application proceeds to normal review
            alert.status = AlertStatus.RESOLVED
            alert.resolved_by = reviewer_id
            emit = True
        elif decision == ReviewDecision.INSUFFICIENT_EVIDENCE:
            advance(ApplicationStatus.UNDER_INVESTIGATION)
            alert.status = AlertStatus.INVESTIGATING  # re-investigate
        # NEED_MORE_REVIEW: leave alert REVIEW_PENDING (re-queue), no state change.

        await self.audit.record(
            action=AuditAction.REVIEW_DECISION, entity_type="review_decision", entity_id=record.id,
            actor_id=reviewer_id,
            after={"alert_id": alert.id, "decision": decision.value, "fp_reason": fp_reason_code.value if fp_reason_code else None},
        )

        if emit:
            stage(self.session, ev.review_decision_recorded(
                new_id(), alert.id, application_id=alert.application_id,
                decision=decision.value, report_id=report_id))

        await self.session.commit()
        if emit:
            try:
                await publish_pending(self.session)
            except Exception as exc:  # noqa: BLE001
                log.warning("events.relay_failed", error=str(exc))
            # Trigger idempotent closed-loop learning. Enqueued directly (reliable across the
            # in-process and Kafka event backends); the task is safe to redeliver.
            try:
                from app.tasks.learning import learn_from_review

                learn_from_review.delay(alert.id, alert.application_id, decision.value)
            except Exception as exc:  # noqa: BLE001 - no broker in dev/test is fine
                log.warning("learning.enqueue_failed", alert_id=alert.id, error=str(exc))
        log.info("review.decision_recorded", alert_id=alert.id, decision=decision.value)
        return record

    async def _record_false_positive(self, alert, record, fp_reason_code, app) -> None:
        signals = (
            await self.session.execute(
                select(FraudSignal).where(
                    FraudSignal.application_id == alert.application_id,
                    FraudSignal.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        self.session.add(FalsePositiveRecord(
            alert_id=alert.id, review_decision_id=record.id, application_id=alert.application_id,
            signal_names=[s.signal_type.value for s in signals],
            risk_score=app.current_risk_score if app else None,
            analyst_explanation=record.comments or "",
            fp_reason_code=fp_reason_code, final_outcome="PROCEEDS",
        ))

    async def review_queue(self) -> list[FraudAlert]:
        rows = (
            await self.session.execute(
                select(FraudAlert)
                .where(FraudAlert.status == AlertStatus.REVIEW_PENDING, FraudAlert.deleted_at.is_(None))
                .order_by(FraudAlert.created_at.asc())
            )
        ).scalars().all()
        return list(rows)
