"""Durable event outbox (transactional-outbox pattern, Phase 8).

A domain event row is staged in the SAME transaction as the business change that
produced it, so an event is never lost if the business write committed. A relay then
publishes PENDING rows to Kafka and marks them SENT; the reconciliation job re-publishes
anything still PENDING/FAILED. Payload is PII-free (IDs + correlation_id + safe scalars).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import EventStatus, EventType


class EventLog(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "event_log"

    event_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False)
    event_type: Mapped[EventType] = mapped_column(
        SAEnum(EventType, native_enum=False, length=48), index=True, nullable=False
    )
    event_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    topic: Mapped[str] = mapped_column(String(128), nullable=False)

    aggregate_type: Mapped[str] = mapped_column(String(48), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)

    payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    status: Mapped[EventStatus] = mapped_column(
        SAEnum(EventStatus, native_enum=False, length=16),
        default=EventStatus.PENDING,
        index=True,
        nullable=False,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<EventLog {self.event_type.value} {self.status.value}>"
