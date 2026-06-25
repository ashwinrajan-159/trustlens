"""Fraud-alert endpoints (Phase 10). Analyst-level; FMR report is senior-only."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.database import get_db
from app.dependencies import CurrentUser, require_analyst, require_senior
from app.models.application import Application
from app.models.enums import AlertStatus, SignalSeverity
from app.models.fraud_alert import FraudAlert
from app.schemas.casework import AlertPublic, FMRReportResponse, ResolveAlertRequest
from app.schemas.common import ERROR_RESPONSES, Page
from app.schemas.fraudops import ClaimResponse, TransitionRequest
from app.services import rbi
from app.services.alerting import AlertingService

router = APIRouter(prefix="/alerts", tags=["alerts"], responses=ERROR_RESPONSES)


@router.get("", response_model=Page[AlertPublic])
async def list_alerts(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: AlertStatus | None = Query(None),
    severity: SignalSeverity | None = Query(None),
    _: CurrentUser = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
) -> Page[AlertPublic]:
    base = select(FraudAlert).where(FraudAlert.deleted_at.is_(None))
    if status is not None:
        base = base.where(FraudAlert.status == status)
    if severity is not None:
        base = base.where(FraudAlert.severity == severity)
    total = (await db.execute(base.with_only_columns(func.count()).order_by(None))).scalar_one()
    rows = (
        await db.execute(base.order_by(FraudAlert.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    ).scalars().all()
    return Page[AlertPublic](
        items=[AlertPublic.model_validate(a) for a in rows], total=total, page=page, page_size=page_size
    )


@router.get("/{alert_id}", response_model=AlertPublic)
async def get_alert(
    alert_id: str, _: CurrentUser = Depends(require_analyst), db: AsyncSession = Depends(get_db)
) -> AlertPublic:
    alert = await AlertingService(db)._get(alert_id)
    return AlertPublic.model_validate(alert)


@router.post("/{alert_id}/acknowledge", response_model=AlertPublic)
async def acknowledge_alert(
    alert_id: str, user: CurrentUser = Depends(require_analyst), db: AsyncSession = Depends(get_db)
) -> AlertPublic:
    return AlertPublic.model_validate(await AlertingService(db).acknowledge(alert_id, by=user.id))


@router.post("/{alert_id}/resolve", response_model=AlertPublic)
async def resolve_alert(
    alert_id: str, data: ResolveAlertRequest,
    user: CurrentUser = Depends(require_analyst), db: AsyncSession = Depends(get_db),
) -> AlertPublic:
    alert = await AlertingService(db).resolve(alert_id, by=user.id, dismiss=data.dismiss)
    return AlertPublic.model_validate(alert)


@router.post("/{alert_id}/claim", response_model=ClaimResponse)
async def claim_alert(
    alert_id: str, user: CurrentUser = Depends(require_analyst), db: AsyncSession = Depends(get_db)
) -> ClaimResponse:
    """Claim an alert for investigation (concurrency-safe — only one analyst wins)."""
    alert = await AlertingService(db).claim(alert_id, by=user.id)
    return ClaimResponse(
        id=alert.id, status=alert.status.value, claimed_by=alert.claimed_by, claimed_at=alert.claimed_at
    )


@router.post("/{alert_id}/transition", response_model=AlertPublic)
async def transition_alert(
    alert_id: str, data: TransitionRequest,
    user: CurrentUser = Depends(require_analyst), db: AsyncSession = Depends(get_db),
) -> AlertPublic:
    """Guarded alert state transition (illegal moves rejected; reopen requires a reason)."""
    alert = await AlertingService(db).transition(
        alert_id, AlertStatus(data.target_status), by=user.id, reason=data.reason or None
    )
    return AlertPublic.model_validate(alert)


@router.get("/{alert_id}/fmr-report", response_model=FMRReportResponse)
async def fmr_report(
    alert_id: str, _: CurrentUser = Depends(require_senior), db: AsyncSession = Depends(get_db)
) -> FMRReportResponse:
    alert = (await db.execute(select(FraudAlert).where(FraudAlert.id == alert_id))).scalar_one_or_none()
    if not alert:
        raise NotFoundError("Alert not found")
    app = (await db.execute(select(Application).where(Application.id == alert.application_id))).scalar_one_or_none()
    amount = float(app.loan_amount_requested) if app else 0.0
    report = rbi.build_fmr_report(
        alert_number=alert.alert_number,
        application_number=app.application_number if app else "UNKNOWN",
        amount=amount,
        classification=rbi.classify(amount),
        risk_tier=app.risk_tier.value if (app and app.risk_tier) else None,
        generated_at=datetime.now(UTC).isoformat(),
    )
    return FMRReportResponse(report=report)
