"""Investigation-case service (Phase 10): create, list, assign, close."""
from __future__ import annotations

import secrets
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.core.security import new_id
from app.events import schemas as ev
from app.events.service import publish_pending, stage
from app.models.enums import CasePriority, CaseStatus, CaseType
from app.models.investigation_case import InvestigationCase

log = get_logger(__name__)


def _case_number() -> str:
    ts = datetime.now(UTC).strftime("%Y%m%d")
    return f"CS-{ts}-{secrets.token_hex(4).upper()}"


class CaseService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self, *, case_type: CaseType, summary: str, priority: CasePriority = CasePriority.MEDIUM,
        application_ids: list[str] | None = None, alert_ids: list[str] | None = None,
        assigned_to: str | None = None,
    ) -> InvestigationCase:
        case = InvestigationCase(
            case_number=_case_number(), case_type=case_type, status=CaseStatus.OPEN,
            priority=priority, summary=summary,
            application_ids=application_ids or [], alert_ids=alert_ids or [],
            assigned_to=assigned_to,
        )
        self.session.add(case)
        await self.session.flush()
        stage(self.session, ev.case_created(
            new_id(), case.id, case_type=case_type.value, priority=priority.value))
        await self.session.commit()
        try:
            await publish_pending(self.session)
        except Exception as exc:  # noqa: BLE001
            log.warning("events.relay_failed", error=str(exc))
        log.info("case.created", case_number=case.case_number)
        return case

    async def get(self, case_id: str) -> InvestigationCase:
        case = (
            await self.session.execute(select(InvestigationCase).where(InvestigationCase.id == case_id))
        ).scalar_one_or_none()
        if not case:
            raise NotFoundError("Case not found")
        return case

    async def list(self, *, status: CaseStatus | None = None, offset: int = 0, limit: int = 50):
        stmt = select(InvestigationCase).where(InvestigationCase.deleted_at.is_(None))
        if status is not None:
            stmt = stmt.where(InvestigationCase.status == status)
        stmt = stmt.order_by(InvestigationCase.created_at.desc()).offset(offset).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def assign(self, case_id: str, *, assignee: str) -> InvestigationCase:
        case = await self.get(case_id)
        case.assigned_to = assignee
        if case.status == CaseStatus.OPEN:
            case.status = CaseStatus.IN_PROGRESS
        await self.session.commit()
        return case

    async def close(self, case_id: str, *, by: str, outcome: str) -> InvestigationCase:
        case = await self.get(case_id)
        if case.status == CaseStatus.CLOSED:
            raise ConflictError("Case is already closed")
        case.status = CaseStatus.CLOSED
        case.closed_at = datetime.now(UTC)
        case.closed_by = by
        case.closed_outcome = outcome
        stage(self.session, ev.case_closed(new_id(), case.id, outcome=outcome))
        await self.session.commit()
        try:
            await publish_pending(self.session)
        except Exception as exc:  # noqa: BLE001
            log.warning("events.relay_failed", error=str(exc))
        log.info("case.closed", case_number=case.case_number, outcome=outcome)
        return case
