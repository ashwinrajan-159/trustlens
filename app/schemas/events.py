"""Event-log (outbox) response schemas. Payload is PII-free by construction."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import EventStatus, EventType


class EventLogPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_id: str
    event_type: EventType
    event_version: int
    topic: str
    aggregate_type: str
    aggregate_id: str
    correlation_id: str | None
    payload: dict
    status: EventStatus
    attempts: int
    created_at: datetime
    sent_at: datetime | None


class ReplayResult(BaseModel):
    sent: int
    failed: int
    scanned: int
