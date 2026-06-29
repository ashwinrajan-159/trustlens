"""Application service: create, submit, decide — with enforced state machine.

The status transition graph lives in ``enums.APPLICATION_TRANSITIONS``; every change
is validated and audited. Submitting an application is where the analysis pipeline
will be dispatched in Phase 2 (left as a clearly-marked hook here).
"""
from __future__ import annotations

import secrets
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AuthorizationError,
    NotFoundError,
    StateTransitionError,
    ValidationError,
)
from app.core.logging import get_logger
from app.core.security import new_id
from app.events import schemas as ev
from app.events.service import publish_pending, stage
from app.models.application import Application
from app.models.enums import (
    ANALYST_ROLES,
    APPLICATION_TRANSITIONS,
    ApplicationStatus,
    AuditAction,
    LoanType,
    UserRole,
)
from app.repositories.application import ApplicationRepository
from app.services.audit import AuditService

log = get_logger(__name__)


async def _relay(session) -> None:
    """Best-effort relay of staged events after commit (no-op-safe)."""
    try:
        await publish_pending(session)
    except Exception as exc:  # noqa: BLE001
        log.warning("events.relay_failed", error=str(exc))


def _generate_application_number() -> str:
    ts = datetime.now(UTC).strftime("%Y%m%d")
    return f"TL-{ts}-{secrets.token_hex(4).upper()}"


class ApplicationService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.apps = ApplicationRepository(session)
        self.audit = AuditService(session)

    async def create(
        self, *, applicant_id: str, loan_type: LoanType, loan_amount: float, ip: str | None = None
    ) -> Application:
        # Retry on the (rare) application_number unique-collision instead of a 500 (#8).
        last_exc: Exception | None = None
        for _ in range(5):
            app = Application(
                application_number=_generate_application_number(),
                applicant_id=applicant_id,
                loan_type=loan_type,
                loan_amount_requested=loan_amount,
                status=ApplicationStatus.DRAFT,
            )
            self.session.add(app)
            try:
                await self.session.flush()
            except IntegrityError as exc:
                last_exc = exc
                await self.session.rollback()
                continue
            await self.audit.record(
                action=AuditAction.CREATE, entity_type="application", entity_id=app.id,
                actor_id=applicant_id, after={"status": app.status.value}, ip_address=ip,
            )
            stage(self.session, ev.application_created(
                new_id(), app.id, applicant_id=applicant_id, loan_type=loan_type.value))
            await self.session.commit()
            await _relay(self.session)
            log.info("application.create", application_id=app.id, applicant_id=applicant_id)
            return app
        raise last_exc or RuntimeError("Could not allocate an application number")

    async def get_for_user(
        self, app_id: str, *, user_id: str, role: UserRole, record_access: bool = False
    ) -> Application:
        app = await self.apps.get(app_id)
        if not app:
            raise NotFoundError("Application not found")
        # Customers may only see their own; analysts/admins see all.
        if role == UserRole.CUSTOMER and app.applicant_id != user_id:
            raise AuthorizationError("You do not have access to this application")
        # Audit PII reads: an analyst viewing someone else's application (#11).
        if record_access and role in ANALYST_ROLES and app.applicant_id != user_id:
            await self.audit.record(
                action=AuditAction.READ_PII, entity_type="application", entity_id=app.id,
                actor_id=user_id,
            )
            await self.session.commit()
        return app

    async def delete(
        self, app_id: str, *, user_id: str, role: UserRole, ip: str | None = None
    ) -> None:
        """Soft-delete (withdraw/archive) an application.

        A customer may remove their OWN application only before an analyst acts on it
        (status DRAFT or SUBMITTED) — so a flagged/under-review case can't be made to
        disappear. Analysts/admins may archive any. Soft-delete (sets ``deleted_at``)
        so it drops out of list views while history/audit are preserved.
        """
        from app.models.base import _utcnow

        app = await self.get_for_user(app_id, user_id=user_id, role=role)
        if app.deleted_at is not None:
            raise NotFoundError("Application not found")
        if role == UserRole.CUSTOMER and app.status not in (
            ApplicationStatus.DRAFT, ApplicationStatus.SUBMITTED,
        ):
            raise StateTransitionError(
                "This application is already under review and can no longer be deleted."
            )
        before = app.status.value
        app.deleted_at = _utcnow()
        await self.audit.record(
            action=AuditAction.DELETE, entity_type="application", entity_id=app.id,
            actor_id=user_id, before={"status": before}, ip_address=ip,
        )
        await self.session.commit()
        log.info("application.delete", application_id=app.id, status=before)

    def _transition(self, app: Application, target: ApplicationStatus) -> None:
        allowed = APPLICATION_TRANSITIONS.get(app.status, set())
        if target not in allowed:
            raise StateTransitionError(
                f"Cannot move application from {app.status.value} to {target.value}"
            )

    async def _present_doc_types(self, app_id: str) -> set[str]:
        """Document types currently attached to the application (any OCR status)."""
        from sqlalchemy import select

        from app.models.document import Document

        rows = (
            await self.session.execute(
                select(Document.document_type).where(
                    Document.application_id == app_id,
                    Document.deleted_at.is_(None),
                    Document.is_current_version.is_(True),
                )
            )
        ).scalars().all()
        return {getattr(t, "value", t) for t in rows}

    async def get_requirements(self, app_id: str, *, user_id: str, role: UserRole) -> dict:
        """Per-loan-type required-document checklist with live satisfaction status."""
        from app.services.cross_document import evaluate_requirements

        app = await self.get_for_user(app_id, user_id=user_id, role=role)
        present = await self._present_doc_types(app_id)
        return evaluate_requirements(app.loan_type.value, present)

    async def submit(self, app_id: str, *, user_id: str, role: UserRole, ip: str | None = None) -> Application:
        from app.services.cross_document import evaluate_requirements

        app = await self.get_for_user(app_id, user_id=user_id, role=role)

        # Gate: the loan type's mandatory documents must be attached before submission.
        present = await self._present_doc_types(app_id)
        req = evaluate_requirements(app.loan_type.value, present)
        if not req["satisfied"]:
            raise ValidationError(
                f"Cannot submit a {app.loan_type.value} loan application — "
                "missing required documents: " + "; ".join(req["missing_required"])
            )

        before = app.status.value
        self._transition(app, ApplicationStatus.SUBMITTED)
        app.status = ApplicationStatus.SUBMITTED
        app.submitted_at = datetime.now(UTC)
        await self.audit.record(
            action=AuditAction.STATE_TRANSITION, entity_type="application", entity_id=app.id,
            actor_id=user_id, before={"status": before}, after={"status": app.status.value},
            ip_address=ip,
        )
        stage(self.session, ev.application_submitted(new_id(), app.id))
        await self.session.commit()
        await _relay(self.session)
        # ── Phase 2 hook: dispatch the 14-step Celery analysis pipeline here. ──
        log.info("application.submit", application_id=app.id)
        return app

    async def decide(
        self, app_id: str, *, approve: bool, reason: str, decided_by: str, ip: str | None = None
    ) -> Application:
        app = await self.apps.get(app_id)
        if not app:
            raise NotFoundError("Application not found")
        target = ApplicationStatus.APPROVED if approve else ApplicationStatus.REJECTED
        before = app.status.value
        self._transition(app, target)
        app.status = target
        app.decision_at = datetime.now(UTC)
        app.decision_by = decided_by
        app.decision_reason = reason
        await self.audit.record(
            action=AuditAction.STATE_TRANSITION, entity_type="application", entity_id=app.id,
            actor_id=decided_by, before={"status": before}, after={"status": target.value},
            ip_address=ip,
        )
        stage(self.session, ev.analyst_decision_made(
            new_id(), app.id, decision=target.value, decided_by=decided_by))
        await self.session.commit()
        await _relay(self.session)

        # Harvest a training label from the analyst's decision (reject=fraud, approve=legit).
        try:
            from app.models.enums import MLLabelSource
            from app.services.ml import MLService

            await MLService(self.session).record_label(
                app.id, 1 if not approve else 0,
                source=MLLabelSource.ANALYST_DECISION, created_by=decided_by,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("ml.label_failed", application_id=app.id, error=str(exc))

        log.info("application.decide", application_id=app.id, decision=target.value)
        return app

    async def list_signals(self, app_id: str, *, user_id: str, role: UserRole):
        """Fraud signals for an application (authorized; highest severity first)."""
        from sqlalchemy import case, select

        from app.models.enums import SignalSeverity
        from app.models.fraud_signal import FraudSignal

        await self.get_for_user(app_id, user_id=user_id, role=role)
        order = case(
            {
                SignalSeverity.CRITICAL: 0, SignalSeverity.HIGH: 1,
                SignalSeverity.MEDIUM: 2, SignalSeverity.LOW: 3,
            },
            value=FraudSignal.severity,
        )
        stmt = (
            select(FraudSignal)
            .where(FraudSignal.application_id == app_id, FraudSignal.deleted_at.is_(None))
            .order_by(order, FraudSignal.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_graph_analysis(self, app_id: str, *, user_id: str, role: UserRole):
        """Latest graph-analysis snapshot for an application (authorized)."""
        from sqlalchemy import select

        from app.models.graph_analysis import GraphAnalysis

        await self.get_for_user(app_id, user_id=user_id, role=role)
        stmt = (
            select(GraphAnalysis)
            .where(GraphAnalysis.application_id == app_id, GraphAnalysis.deleted_at.is_(None))
            .order_by(GraphAnalysis.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def get_network(self, app_id: str, *, user_id: str, role: UserRole) -> dict:
        """Per-application entity network (nodes/edges, PII masked) for the analyst UI."""
        from app.services import graph_intel
        from app.tasks.graph import load_records

        await self.get_for_user(app_id, user_id=user_id, role=role)
        records = await load_records(self.session)
        graph = graph_intel.build_graph(records)
        return graph_intel.ego_network(graph, app_id)

    async def get_property(self, app_id: str, *, user_id: str, role: UserRole):
        """Latest property/collateral profile for an application (authorized)."""
        from sqlalchemy import select

        from app.models.property_profile import PropertyProfile

        await self.get_for_user(app_id, user_id=user_id, role=role)
        stmt = (
            select(PropertyProfile)
            .where(PropertyProfile.application_id == app_id, PropertyProfile.deleted_at.is_(None))
            .order_by(PropertyProfile.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def get_financial(self, app_id: str, *, user_id: str, role: UserRole):
        """Latest business/financial profile for an application (authorized)."""
        from sqlalchemy import select

        from app.models.business_profile import BusinessProfile

        await self.get_for_user(app_id, user_id=user_id, role=role)
        stmt = (
            select(BusinessProfile)
            .where(BusinessProfile.application_id == app_id, BusinessProfile.deleted_at.is_(None))
            .order_by(BusinessProfile.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def get_completeness(self, app_id: str, *, user_id: str, role: UserRole) -> dict:
        """Document-completeness summary for an application (authorized)."""
        from sqlalchemy import select

        from app.models.document import Document
        from app.models.enums import DocumentStatus
        from app.services.cross_document import compute_completeness

        app = await self.get_for_user(app_id, user_id=user_id, role=role)
        docs = (
            await self.session.execute(
                select(Document).where(
                    Document.application_id == app_id,
                    Document.deleted_at.is_(None),
                    Document.is_current_version.is_(True),
                    Document.status == DocumentStatus.PROCESSED,
                )
            )
        ).scalars().all()
        present = sorted({d.document_type.value for d in docs})
        missing_critical, missing_recommended = compute_completeness(app.loan_type.value, set(present))
        return {
            "loan_type": app.loan_type,
            "present": present,
            "missing_critical": missing_critical,
            "missing_recommended": missing_recommended,
            "is_complete": not missing_critical,
        }

    async def get_identity(self, app_id: str, *, user_id: str, role: UserRole):
        """Latest resolved identity profile for an application (authorized)."""
        from sqlalchemy import select

        from app.models.identity_profile import IdentityProfile

        await self.get_for_user(app_id, user_id=user_id, role=role)
        stmt = (
            select(IdentityProfile)
            .where(IdentityProfile.application_id == app_id, IdentityProfile.deleted_at.is_(None))
            .order_by(IdentityProfile.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def get_risk(self, app_id: str, *, user_id: str, role: UserRole):
        """Latest risk assessment for an application (authorized)."""
        from sqlalchemy import select

        from app.models.risk_assessment import RiskAssessment

        await self.get_for_user(app_id, user_id=user_id, role=role)
        stmt = (
            select(RiskAssessment)
            .where(RiskAssessment.application_id == app_id, RiskAssessment.deleted_at.is_(None))
            .order_by(RiskAssessment.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def list_for_user(
        self,
        *,
        user_id: str,
        role: UserRole,
        offset: int,
        limit: int,
        status: ApplicationStatus | None = None,
        loan_type: LoanType | None = None,
        sort: str = "-created_at",
    ) -> tuple[list[Application], int]:
        # Customers are scoped to their own applications; analysts see all (#21 filters).
        scoped_applicant = user_id if role == UserRole.CUSTOMER else None
        return await self.apps.query(
            applicant_id=scoped_applicant,
            status=status,
            loan_type=loan_type,
            sort=sort,
            offset=offset,
            limit=limit,
        )
