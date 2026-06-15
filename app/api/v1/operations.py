"""Operations endpoints (Phase 8): event-log visibility + manual reconciliation.

Analyst-only. The event log is the durable outbox; the replay endpoint triggers the same
reconciliation the scheduled job runs.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import CurrentUser, require_analyst
from app.events.service import publish_pending
from app.models.enums import EventStatus
from app.models.event_log import EventLog
from app.schemas.common import ERROR_RESPONSES, Page
from app.schemas.events import EventLogPublic, ReplayResult

router = APIRouter(prefix="/operations", tags=["operations"], responses=ERROR_RESPONSES)


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
