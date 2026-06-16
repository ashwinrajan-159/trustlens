"""ML platform endpoints (Phase 9). Local models only.

Training/approval/promotion are SENIOR-only (model governance with human approval); reads,
labels, prediction and drift are analyst-level. ``/ml/predict`` is rate-limited (spec §14).
ML output is advisory — surfaced next to the deterministic score, never replacing it.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.ratelimit import rate_limit
from app.database import get_db
from app.dependencies import CurrentUser, require_analyst, require_senior
from app.models.ml import MLModel, MLPrediction
from app.schemas.common import ERROR_RESPONSES, MessageResponse
from app.schemas.ml import (
    DriftResponse,
    LabelCreate,
    MLModelPublic,
    MLPredictionPublic,
    RejectRequest,
    TrainRequest,
)
from app.services.ml import MLService

router = APIRouter(prefix="/ml", tags=["ml"], responses=ERROR_RESPONSES)


@router.post("/train", response_model=MLModelPublic, status_code=201)
async def train(
    data: TrainRequest,
    _: CurrentUser = Depends(require_senior),
    db: AsyncSession = Depends(get_db),
) -> MLModelPublic:
    model = await MLService(db).train(name=data.name, algorithm=data.algorithm)
    return MLModelPublic.model_validate(model)


@router.get("/models", response_model=list[MLModelPublic])
async def list_models(
    _: CurrentUser = Depends(require_analyst), db: AsyncSession = Depends(get_db)
) -> list[MLModelPublic]:
    rows = (
        await db.execute(
            select(MLModel).where(MLModel.deleted_at.is_(None)).order_by(MLModel.created_at.desc())
        )
    ).scalars().all()
    return [MLModelPublic.model_validate(m) for m in rows]


@router.get("/models/{model_id}", response_model=MLModelPublic)
async def get_model(
    model_id: str, _: CurrentUser = Depends(require_analyst), db: AsyncSession = Depends(get_db)
) -> MLModelPublic:
    model = await MLService(db)._get_model(model_id)
    return MLModelPublic.model_validate(model)


@router.post("/models/{model_id}/approve", response_model=MLModelPublic)
async def approve_model(
    model_id: str, user: CurrentUser = Depends(require_senior), db: AsyncSession = Depends(get_db)
) -> MLModelPublic:
    model = await MLService(db).approve(model_id, approver=user.id)
    return MLModelPublic.model_validate(model)


@router.post("/models/{model_id}/reject", response_model=MLModelPublic)
async def reject_model(
    model_id: str, data: RejectRequest,
    user: CurrentUser = Depends(require_senior), db: AsyncSession = Depends(get_db),
) -> MLModelPublic:
    model = await MLService(db).reject(model_id, approver=user.id, reason=data.reason)
    return MLModelPublic.model_validate(model)


@router.post("/models/{model_id}/promote", response_model=MLModelPublic)
async def promote_model(
    model_id: str, _: CurrentUser = Depends(require_senior), db: AsyncSession = Depends(get_db)
) -> MLModelPublic:
    model = await MLService(db).promote(model_id)
    return MLModelPublic.model_validate(model)


@router.post(
    "/predict/{application_id}",
    response_model=MLPredictionPublic,
    dependencies=[Depends(rate_limit("ml_predict", settings.rate_limit_auth))],
)
async def predict(
    application_id: str, _: CurrentUser = Depends(require_analyst), db: AsyncSession = Depends(get_db)
) -> MLPredictionPublic:
    pred = await MLService(db).predict(application_id)
    return MLPredictionPublic.model_validate(pred)


@router.get("/explain/{application_id}", response_model=MLPredictionPublic | None)
async def explain(
    application_id: str, _: CurrentUser = Depends(require_analyst), db: AsyncSession = Depends(get_db)
) -> MLPredictionPublic | None:
    pred = (
        await db.execute(
            select(MLPrediction)
            .where(MLPrediction.application_id == application_id)
            .order_by(MLPrediction.created_at.desc()).limit(1)
        )
    ).scalars().first()
    return MLPredictionPublic.model_validate(pred) if pred else None


@router.post("/labels", response_model=MessageResponse, status_code=201)
async def add_label(
    data: LabelCreate, user: CurrentUser = Depends(require_analyst), db: AsyncSession = Depends(get_db)
) -> MessageResponse:
    await MLService(db).record_label(
        data.application_id, data.label, source=data.source, created_by=user.id
    )
    return MessageResponse(message="Label recorded")


@router.get("/drift", response_model=DriftResponse)
async def drift(
    _: CurrentUser = Depends(require_analyst), db: AsyncSession = Depends(get_db)
) -> DriftResponse:
    return DriftResponse(**(await MLService(db).drift()))
