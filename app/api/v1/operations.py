"""Operations endpoints (Phase 8): event-log visibility + manual reconciliation.

Analyst-only. The event log is the durable outbox; the replay endpoint triggers the same
reconciliation the scheduled job runs.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import CurrentUser, require_analyst
from app.events.service import publish_pending
from app.models.application import Application
from app.models.enums import AlertStatus, CaseStatus, EventStatus, RBIReportType, SignalSeverity
from app.models.event_log import EventLog
from app.models.fraud_alert import FraudAlert
from app.models.investigation_case import InvestigationCase
from app.schemas.casework import AlertPublic, OperationsOverview
from app.schemas.common import ERROR_RESPONSES, Page
from app.schemas.events import EventLogPublic, ReplayResult
from app.services.alerting import AlertingService

router = APIRouter(prefix="/operations", tags=["operations"], responses=ERROR_RESPONSES)

_OPEN_ALERTS = {AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED, AlertStatus.ESCALATED}


@router.get("/events", response_model=Page[EventLogPublic])
async def list_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: EventStatus | None = Query(None),
    _: CurrentUser = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
) -> Page[EventLogPublic]:
    offset = (page - 1) * page_size
    base = select(EventLog)
    if status is not None:
        base = base.where(EventLog.status == status)

    from sqlalchemy import func

    total = (await db.execute(base.with_only_columns(func.count()).order_by(None))).scalar_one()
    rows = (
        await db.execute(base.order_by(EventLog.created_at.desc()).offset(offset).limit(page_size))
    ).scalars().all()
    return Page[EventLogPublic](
        items=[EventLogPublic.model_validate(r) for r in rows],
        total=total, page=page, page_size=page_size,
    )


@router.post("/events/replay", response_model=ReplayResult)
async def replay_events(
    _: CurrentUser = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
) -> ReplayResult:
    result = await publish_pending(db, limit=500)
    return ReplayResult(**result)


async def _count(db, stmt) -> int:
    return (await db.execute(stmt.with_only_columns(func.count()).order_by(None))).scalar_one()


@router.get("/overview", response_model=OperationsOverview)
async def overview(
    _: CurrentUser = Depends(require_analyst), db: AsyncSession = Depends(get_db)
) -> OperationsOverview:
    apps = select(Application).where(Application.deleted_at.is_(None))
    by_tier: dict[str, int] = {}
    for tier, n in (
        await db.execute(
            select(Application.risk_tier, func.count())
            .where(Application.deleted_at.is_(None), Application.risk_tier.is_not(None))
            .group_by(Application.risk_tier)
        )
    ).all():
        by_tier[tier.value if hasattr(tier, "value") else str(tier)] = n

    alerts_open = select(FraudAlert).where(
        FraudAlert.deleted_at.is_(None), FraudAlert.status.in_(_OPEN_ALERTS)
    )
    return OperationsOverview(
        applications_total=await _count(db, apps),
        applications_by_tier=by_tier,
        alerts_open=await _count(db, alerts_open),
        alerts_rbi_reportable=await _count(
            db, alerts_open.where(FraudAlert.rbi_report_type != RBIReportType.NONE)
        ),
        alerts_sla_breached=await _count(
            db, select(FraudAlert).where(FraudAlert.deleted_at.is_(None), FraudAlert.sla_breached.is_(True))
        ),
        cases_open=await _count(
            db, select(InvestigationCase).where(
                InvestigationCase.deleted_at.is_(None), InvestigationCase.status != CaseStatus.CLOSED
            )
        ),
    )


@router.get("/active-threats", response_model=list[AlertPublic])
async def active_threats(
    _: CurrentUser = Depends(require_analyst), db: AsyncSession = Depends(get_db)
) -> list[AlertPublic]:
    rows = (
        await db.execute(
            select(FraudAlert).where(
                FraudAlert.deleted_at.is_(None),
                FraudAlert.status.in_(_OPEN_ALERTS),
                FraudAlert.severity.in_([SignalSeverity.CRITICAL, SignalSeverity.HIGH]),
            ).order_by(FraudAlert.created_at.desc())
        )
    ).scalars().all()
    return [AlertPublic.model_validate(a) for a in rows]


@router.get("/sla-breaches", response_model=list[AlertPublic])
async def sla_breaches(
    _: CurrentUser = Depends(require_analyst), db: AsyncSession = Depends(get_db)
) -> list[AlertPublic]:
    await AlertingService(db).mark_sla_breaches()  # refresh flags first
    rows = (
        await db.execute(
            select(FraudAlert).where(
                FraudAlert.deleted_at.is_(None), FraudAlert.sla_breached.is_(True)
            ).order_by(FraudAlert.sla_deadline.asc())
        )
    ).scalars().all()
    return [AlertPublic.model_validate(a) for a in rows]
