"""Application endpoints: create, list, get, submit, decide."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import CurrentUser, client_ip, get_current_user, require_analyst
from app.models.enums import ApplicationStatus, LoanType
from app.schemas.application import (
    ApplicationCreate,
    ApplicationDecision,
    ApplicationPublic,
)
from app.schemas.common import ERROR_RESPONSES, Page
from app.schemas.risk import (
    BusinessProfilePublic,
    CompletenessResponse,
    FraudSignalPublic,
    GraphAnalysisPublic,
    IdentityProfilePublic,
    NetworkResponse,
    PropertyProfilePublic,
    RiskAssessmentPublic,
)
from app.services.application import ApplicationService

router = APIRouter(prefix="/applications", tags=["applications"], responses=ERROR_RESPONSES)


@router.post("", response_model=ApplicationPublic, status_code=201)
async def create_application(
    data: ApplicationCreate,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApplicationPublic:
    app = await ApplicationService(db).create(
        applicant_id=user.id,
        loan_type=data.loan_type,
        loan_amount=float(data.loan_amount_requested),
        ip=client_ip(request),
    )
    return ApplicationPublic.model_validate(app)


@router.get("", response_model=Page[ApplicationPublic])
async def list_applications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: ApplicationStatus | None = Query(None),
    loan_type: LoanType | None = Query(None),
    sort: str = Query("-created_at", pattern="^-?created_at$"),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page[ApplicationPublic]:
    offset = (page - 1) * page_size
    items, total = await ApplicationService(db).list_for_user(
        user_id=user.id, role=user.role, offset=offset, limit=page_size,
        status=status, loan_type=loan_type, sort=sort,
    )
    return Page[ApplicationPublic](
        items=[ApplicationPublic.model_validate(a) for a in items],
        total=total, page=page, page_size=page_size,
    )


@router.get("/{application_id}", response_model=ApplicationPublic)
async def get_application(
    application_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApplicationPublic:
    app = await ApplicationService(db).get_for_user(
        application_id, user_id=user.id, role=user.role, record_access=True
    )
    return ApplicationPublic.model_validate(app)


@router.delete("/{application_id}", status_code=204)
async def delete_application(
    application_id: str,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Withdraw/archive an application (owner pre-review, or analyst); soft-delete, audited."""
    await ApplicationService(db).delete(
        application_id, user_id=user.id, role=user.role, ip=client_ip(request)
    )
    return Response(status_code=204)


@router.get("/{application_id}/signals", response_model=list[FraudSignalPublic])
async def list_signals(
    application_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[FraudSignalPublic]:
    signals = await ApplicationService(db).list_signals(
        application_id, user_id=user.id, role=user.role
    )
    return [FraudSignalPublic.model_validate(s) for s in signals]


@router.get("/{application_id}/risk", response_model=RiskAssessmentPublic | None)
async def get_risk(
    application_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RiskAssessmentPublic | None:
    risk = await ApplicationService(db).get_risk(
        application_id, user_id=user.id, role=user.role
    )
    return RiskAssessmentPublic.model_validate(risk) if risk else None


@router.get("/{application_id}/completeness", response_model=CompletenessResponse)
async def get_completeness(
    application_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CompletenessResponse:
    data = await ApplicationService(db).get_completeness(
        application_id, user_id=user.id, role=user.role
    )
    return CompletenessResponse(**data)


@router.get("/{application_id}/identity", response_model=IdentityProfilePublic | None)
async def get_identity(
    application_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> IdentityProfilePublic | None:
    profile = await ApplicationService(db).get_identity(
        application_id, user_id=user.id, role=user.role
    )
    return IdentityProfilePublic.model_validate(profile) if profile else None


@router.get("/{application_id}/property", response_model=PropertyProfilePublic | None)
async def get_property(
    application_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PropertyProfilePublic | None:
    profile = await ApplicationService(db).get_property(
        application_id, user_id=user.id, role=user.role
    )
    return PropertyProfilePublic.model_validate(profile) if profile else None


@router.get("/{application_id}/financial", response_model=BusinessProfilePublic | None)
async def get_financial(
    application_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BusinessProfilePublic | None:
    profile = await ApplicationService(db).get_financial(
        application_id, user_id=user.id, role=user.role
    )
    return BusinessProfilePublic.model_validate(profile) if profile else None


@router.get("/{application_id}/graph", response_model=GraphAnalysisPublic | None)
async def get_graph(
    application_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GraphAnalysisPublic | None:
    analysis = await ApplicationService(db).get_graph_analysis(
        application_id, user_id=user.id, role=user.role
    )
    return GraphAnalysisPublic.model_validate(analysis) if analysis else None


@router.get("/{application_id}/network", response_model=NetworkResponse)
async def get_network(
    application_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NetworkResponse:
    data = await ApplicationService(db).get_network(
        application_id, user_id=user.id, role=user.role
    )
    return NetworkResponse(**data)


@router.get("/{application_id}/regulatory-report")
async def regulatory_report(
    application_id: str,
    request: Request,
    user: CurrentUser = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Generate the per-application Regulatory Explainability Report (PDF).

    Analyst+ only. The generation itself is recorded in the WORM audit trail.
    """
    from app.models.enums import AuditAction
    from app.services.audit import AuditService
    from app.services.regulatory_report import RegulatoryReportService

    pdf, filename = await RegulatoryReportService(db).build_pdf(
        application_id, user_id=user.id, role=user.role
    )
    await AuditService(db).record(
        action=AuditAction.DOWNLOAD,
        entity_type="application",
        entity_id=application_id,
        actor_id=user.id,
        after={"artifact": "regulatory_report_pdf", "filename": filename},
        ip_address=client_ip(request),
    )
    await db.commit()
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{application_id}/submit", response_model=ApplicationPublic)
async def submit_application(
    application_id: str,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApplicationPublic:
    app = await ApplicationService(db).submit(
        application_id, user_id=user.id, role=user.role, ip=client_ip(request)
    )
    return ApplicationPublic.model_validate(app)


@router.post("/{application_id}/decision", response_model=ApplicationPublic)
async def decide_application(
    application_id: str,
    data: ApplicationDecision,
    request: Request,
    user: CurrentUser = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
) -> ApplicationPublic:
    app = await ApplicationService(db).decide(
        application_id, approve=data.approve, reason=data.reason,
        decided_by=user.id, ip=client_ip(request),
    )
    return ApplicationPublic.model_validate(app)
