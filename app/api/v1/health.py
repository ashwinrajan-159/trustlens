"""Liveness + readiness probes."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live() -> dict:
    """Process is up."""
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment}


@router.get("/health/ready")
async def ready(db: AsyncSession = Depends(get_db)) -> dict:
    """Dependencies reachable (DB ping). Returns degraded detail, never raises."""
    checks: dict[str, str] = {}
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001 — readiness must report, not crash
        checks["database"] = "unavailable"
    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, "checks": checks}
