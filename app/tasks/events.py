"""Event reconciliation/replay (Phase 8) — required durability backstop.

``replay_pending_events`` re-publishes any event_log rows still PENDING/FAILED (e.g. the
broker was down when they were first staged). Schedule it on Celery beat (e.g. every
minute); it is idempotent and safe to run continuously.
"""
from __future__ import annotations

import asyncio

from app.core.logging import get_logger
from app.database import SessionFactory
from app.events.service import publish_pending
from app.worker import celery_app

log = get_logger(__name__)


async def replay_pending_events_async(*, session_factory=None, limit: int = 500) -> dict:
    sf = session_factory or SessionFactory
    async with sf() as session:
        return await publish_pending(session, limit=limit)


@celery_app.task(name="app.tasks.events.replay_pending_events", bind=True, max_retries=3, default_retry_delay=30)
def replay_pending_events(self) -> dict:
    try:
        return asyncio.run(replay_pending_events_async())
    except Exception as exc:  # pragma: no cover - needs broker
        raise self.retry(exc=exc) from exc
