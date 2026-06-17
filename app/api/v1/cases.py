"""Investigation-case endpoints (Phase 10). Closing a case is senior-only."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import CurrentUser, require_analyst, require_senior
from app.models.enums import CaseStatus
from app.schemas.casework import CaseAssignRequest, CaseCloseRequest, CaseCreate, CasePublic
from app.schemas.common import ERROR_RESPONSES
from app.services.cases import CaseService

router = APIRouter(prefix="/cases", tags=["cases"], responses=ERROR_RESPONSES)


@router.post("", response_model=CasePublic, status_code=201)
async def create_case(
    data: CaseCreate, _: CurrentUser = Depends(require_analyst), db: AsyncSession = Depends(get_db)
) -> CasePublic:
    case = await CaseService(db).create(
        case_type=data.case_type, summary=data.summary, priority=data.priority,
        application_ids=data.application_ids, alert_ids=data.alert_ids,
    )
    return CasePublic.model_validate(case)


@router.get("", response_model=list[CasePublic])
async def list_cases(
    status: CaseStatus | None = Query(None),
    _: CurrentUser = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
) -> list[CasePublic]:
    cases = await CaseService(db).list(status=status)
    return [CasePublic.model_validate(c) for c in cases]


@router.get("/{case_id}", response_model=CasePublic)
async def get_case(
    case_id: str, _: CurrentUser = Depends(require_analyst), db: AsyncSession = Depends(get_db)
) -> CasePublic:
    return CasePublic.model_validate(await CaseService(db).get(case_id))


@router.post("/{case_id}/assign", response_model=CasePublic)
async def assign_case(
    case_id: str, data: CaseAssignRequest,
    _: CurrentUser = Depends(require_analyst), db: AsyncSession = Depends(get_db),
) -> CasePublic:
    return CasePublic.model_validate(await CaseService(db).assign(case_id, assignee=data.assignee))


@router.post("/{case_id}/close", response_model=CasePublic)
async def close_case(
    case_id: str, data: CaseCloseRequest,
    user: CurrentUser = Depends(require_senior), db: AsyncSession = Depends(get_db),
) -> CasePublic:
    case = await CaseService(db).close(case_id, by=user.id, outcome=data.outcome)
    return CasePublic.model_validate(case)
