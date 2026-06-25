"""Fraud-ops closed-loop endpoints (Phase 12).

- Investigations: an analyst who *claimed* an alert submits a report (SoD at the service).
- Reviews: a SENIOR_ANALYST who is **not** the investigator records the final decision.
- Knowledge base + signal analytics: read for analysts; admin may merge patterns.
- Weight governance: anyone analyst+ proposes; an ADMIN who is not the proposer activates.

RBAC is enforced by the role guard on each route; segregation of duties (the same person
cannot investigate-and-review, or propose-and-approve) is enforced inside the services.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import CurrentUser, require_admin, require_analyst, require_senior
from app.schemas.casework import AlertPublic
from app.schemas.common import ERROR_RESPONSES
from app.schemas.fraudops import (
    FraudPatternPublic,
    InvestigationReportCreate,
    InvestigationReportPublic,
    PatternMergeRequest,
    ReviewDecisionCreate,
    ReviewDecisionPublic,
    SignalPerformancePublic,
    WeightConfigPublic,
    WeightProposeRequest,
)
from app.services.fraud_pattern import FraudPatternService
from app.services.investigation import InvestigationService
from app.services.review import ReviewService
from app.services.signal_analytics import SignalAnalyticsService
from app.services.weight_governance import WeightGovernanceService

router = APIRouter(tags=["fraud-ops"], responses=ERROR_RESPONSES)


# ── Investigations ──
@router.post("/alerts/{alert_id}/investigation", response_model=InvestigationReportPublic)
async def submit_investigation(
    alert_id: str, data: InvestigationReportCreate,
    user: CurrentUser = Depends(require_analyst), db: AsyncSession = Depends(get_db),
) -> InvestigationReportPublic:
    report = await InvestigationService(db).submit_report(
        alert_id, underwriter_id=user.id,
        investigation_summary=data.investigation_summary, findings=data.findings,
        evidence=data.evidence, recommendation=data.recommendation,
    )
    return InvestigationReportPublic.model_validate(report)


@router.get("/alerts/{alert_id}/investigations", response_model=list[InvestigationReportPublic])
async def list_investigations(
    alert_id: str, _: CurrentUser = Depends(require_analyst), db: AsyncSession = Depends(get_db)
) -> list[InvestigationReportPublic]:
    reports = await InvestigationService(db).list_for_alert(alert_id)
    return [InvestigationReportPublic.model_validate(r) for r in reports]


# ── Reviews (senior, SoD-enforced) ──
@router.get("/reviews/queue", response_model=list[AlertPublic])
async def review_queue(
    _: CurrentUser = Depends(require_senior), db: AsyncSession = Depends(get_db)
) -> list[AlertPublic]:
    alerts = await ReviewService(db).review_queue()
    return [AlertPublic.model_validate(a) for a in alerts]


@router.post("/reports/{report_id}/review", response_model=ReviewDecisionPublic)
async def record_review(
    report_id: str, data: ReviewDecisionCreate,
    user: CurrentUser = Depends(require_senior), db: AsyncSession = Depends(get_db),
) -> ReviewDecisionPublic:
    record = await ReviewService(db).record_decision(
        report_id, reviewer_id=user.id, decision=data.decision,
        comments=data.comments, fp_reason_code=data.fp_reason_code,
    )
    return ReviewDecisionPublic.model_validate(record)


# ── Knowledge base ──
@router.get("/knowledge/patterns", response_model=list[FraudPatternPublic])
async def list_patterns(
    _: CurrentUser = Depends(require_analyst), db: AsyncSession = Depends(get_db)
) -> list[FraudPatternPublic]:
    patterns = await FraudPatternService(db).list_patterns()
    return [FraudPatternPublic.model_validate(p) for p in patterns]


@router.post("/knowledge/patterns/merge", response_model=FraudPatternPublic)
async def merge_patterns(
    data: PatternMergeRequest, _: CurrentUser = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> FraudPatternPublic:
    target = await FraudPatternService(db).merge(source_id=data.source_id, target_id=data.target_id)
    return FraudPatternPublic.model_validate(target)


# ── Signal analytics ──
@router.get("/signal-analytics", response_model=list[SignalPerformancePublic])
async def signal_analytics(
    _: CurrentUser = Depends(require_analyst), db: AsyncSession = Depends(get_db)
) -> list[SignalPerformancePublic]:
    rows = await SignalAnalyticsService(db).table()
    return [SignalPerformancePublic.model_validate(r) for r in rows]


# ── Weight governance ──
@router.get("/weights", response_model=list[WeightConfigPublic])
async def list_weights(
    _: CurrentUser = Depends(require_analyst), db: AsyncSession = Depends(get_db)
) -> list[WeightConfigPublic]:
    rows = await WeightGovernanceService(db).list_versions()
    return [WeightConfigPublic.model_validate(r) for r in rows]


@router.post("/weights/propose", response_model=WeightConfigPublic)
async def propose_weights(
    data: WeightProposeRequest, user: CurrentUser = Depends(require_senior), db: AsyncSession = Depends(get_db)
) -> WeightConfigPublic:
    cfg = await WeightGovernanceService(db).propose(
        weights=data.weights, rationale=data.rationale, proposed_by=user.id
    )
    return WeightConfigPublic.model_validate(cfg)


@router.post("/weights/{config_id}/activate", response_model=WeightConfigPublic)
async def activate_weights(
    config_id: str, user: CurrentUser = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> WeightConfigPublic:
    cfg = await WeightGovernanceService(db).approve_and_activate(config_id, approver_id=user.id)
    return WeightConfigPublic.model_validate(cfg)
