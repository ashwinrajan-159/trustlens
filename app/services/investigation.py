"""Investigation service (Phase 12).

An analyst who has *claimed* an alert submits a structured investigation report with a
recommendation. This advances the alert INVESTIGATING → REVIEW_PENDING and the application
into REVIEW_PENDING, awaiting a senior reviewer (a different person — SoD enforced at the
review step). Every action is recorded in the existing WORM audit trail.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, ConflictError, NotFoundError
from app.core.logging import get_logger
from app.models.enums import (
    APPLICATION_TRANSITIONS,
    AlertStatus,
    ApplicationStatus,
    AuditAction,
    ReportRecommendation,
)
from app.models.application import Application
from app.models.fraud_alert import FraudAlert
from app.models.fraudops import InvestigationReport
from app.services.audit import AuditService

log = get_logger(__name__)


class InvestigationService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.audit = AuditService(session)

    async def _alert(self, alert_id: str) -> FraudAlert:
        alert = (
            await self.session.execute(select(FraudAlert).where(FraudAlert.id == alert_id))
        ).scalar_one_or_none()
        if not alert:
            raise NotFoundError("Alert not found")
        return alert

    async def submit_report(
        self, alert_id: str, *, underwriter_id: str, investigation_summary: str,
        findings: str = "", evidence: dict | None = None,
        recommendation: ReportRecommendation = ReportRecommendation.REQUEST_INFORMATION,
    ) -> InvestigationReport:
        alert = await self._alert(alert_id)

        # Only the claiming investigator may report on the alert.
        if alert.claimed_by != underwriter_id:
            raise AuthorizationError("Only the analyst who claimed this alert can submit its report")
        if alert.status != AlertStatus.INVESTIGATING:
            raise ConflictError(f"Alert must be INVESTIGATING to submit a report (is {alert.status.value})")

        report = InvestigationReport(
            alert_id=alert_id, case_id=alert.case_id, underwriter_id=underwriter_id,
            investigation_summary=investigation_summary, findings=findings,
            evidence=evidence or {}, recommendation=recommendation,
        )
        self.session.add(report)
        await self.session.flush()

        alert.status = AlertStatus.REVIEW_PENDING
        app = (
            await self.session.execute(select(Application).where(Application.id == alert.application_id))
        ).scalar_one_or_none()
        if app and ApplicationStatus.REVIEW_PENDING in APPLICATION_TRANSITIONS.get(app.status, set()):
            app.status = ApplicationStatus.REVIEW_PENDING

        await self.audit.record(
            action=AuditAction.SUBMIT_REPORT, entity_type="investigation_report", entity_id=report.id,
            actor_id=underwriter_id,
            after={"alert_id": alert_id, "recommendation": recommendation.value},
        )
        await self.session.commit()
        log.info("investigation.report_submitted", alert_id=alert_id, report_id=report.id)
        return report

    async def list_for_alert(self, alert_id: str) -> list[InvestigationReport]:
        rows = (
            await self.session.execute(
                select(InvestigationReport)
                .where(InvestigationReport.alert_id == alert_id, InvestigationReport.deleted_at.is_(None))
                .order_by(InvestigationReport.created_at.desc())
            )
        ).scalars().all()
        return list(rows)

    async def get(self, report_id: str) -> InvestigationReport:
        report = (
            await self.session.execute(select(InvestigationReport).where(InvestigationReport.id == report_id))
        ).scalar_one_or_none()
        if not report:
            raise NotFoundError("Investigation report not found")
        return report
