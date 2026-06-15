"""EventService — transactional outbox + relay/reconciliation (Phase 8).

``stage`` writes the event row into the caller's session (same transaction as the
business change) so the event is durable iff the business write commits. ``relay``
publishes PENDING rows to the broker and marks them SENT (or FAILED with the error +
attempt count). ``publish_pending`` is the reconciliation/replay job — it re-publishes
anything still PENDING/FAILED, so a broker outage never loses events.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import correlation_id_ctx, get_logger
from app.core.security import new_id
from app.events.publisher import EventPublisher, get_publisher
from app.events.schemas import EventEnvelope
from app.models.enums import EventStatus, EventType
from app.models.event_log import EventLog

log = get_logger(__name__)


def stage(session: AsyncSession, envelope: EventEnvelope) -> EventLog:
    """Add an event row to the current transaction (no commit — caller commits)."""
    row = EventLog(
        event_id=envelope.event_id,
        event_type=envelope.event_type,
        event_version=envelope.event_version,
        topic=envelope.topic,
        aggregate_type=envelope.aggregate_type,
        aggregate_id=envelope.aggregate_id,
        correlation_id=envelope.correlation_id or correlation_id_ctx.get(),
        payload=envelope.payload,
        status=EventStatus.PENDING,
    )
    session.add(row)
    return row


def make_event(event_type: EventType, aggregate_type: str, aggregate_id: str, payload: dict, *, version: int = 1) -> EventEnvelope:
    """Convenience envelope builder for callers that don't use a typed builder."""
    return EventEnvelope(
        event_id=new_id(),
        event_type=event_type,
        event_version=version,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        correlation_id=correlation_id_ctx.get(),
        payload=payload,
    )


def _to_envelope(row: EventLog) -> EventEnvelope:
    return EventEnvelope(
        event_id=row.event_id,
        event_type=row.event_type,
        event_version=row.event_version,
        aggregate_type=row.aggregate_type,
        aggregate_id=row.aggregate_id,
        correlation_id=row.correlation_id,
        payload=row.payload,
    )


async def publish_pending(
    session: AsyncSession, *, publisher: EventPublisher | None = None, limit: int = 100
) -> dict:
    """Relay PENDING/FAILED events to the broker (also the reconciliation/replay job).

    Idempotent and safe to run on a schedule: each row is only marked SENT after a
    successful publish; a failure records the error and leaves it for the next pass.
    """
    pub = publisher or get_publisher()
    rows = (
        await session.execute(
            select(EventLog)
            .where(EventLog.status != EventStatus.SENT)
            .order_by(EventLog.created_at.asc())
            .limit(limit)
        )
    ).scalars().all()

    sent = failed = 0
    for row in rows:
        row.attempts += 1
        try:
            await pub.publish(_to_envelope(row))
            row.status = EventStatus.SENT
            row.sent_at = datetime.now(UTC)
            row.last_error = None
            sent += 1
        except Exception as exc:  # noqa: BLE001 - never let one bad event stop the relay
            row.status = EventStatus.FAILED
            row.last_error = str(exc)[:500]
            failed += 1
            log.error("events.publish_failed", event_id=row.event_id, error=str(exc))
    await session.commit()
    if sent or failed:
        log.info("events.relayed", sent=sent, failed=failed)
    return {"sent": sent, "failed": failed, "scanned": len(rows)}
