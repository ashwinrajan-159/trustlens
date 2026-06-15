"""Event publisher abstraction (Phase 8). Local-first; no internet.

- ``InMemoryPublisher`` — dev/test default. Records published events and dispatches them
  to in-process subscribers (the real-time engine), so streaming behaviour is testable
  without a broker.
- ``KafkaPublisher`` — production. Lazily creates an aiokafka producer pointed at the
  LOCAL Kafka broker. Imported only when selected, so aiokafka isn't needed in dev/test.

Selected by ``settings.events_backend`` ("memory" | "kafka"); always "memory" under tests.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from app.config import settings
from app.core.logging import get_logger
from app.events.schemas import EventEnvelope

log = get_logger(__name__)

Subscriber = Callable[[EventEnvelope], Awaitable[None]]


class EventPublisher(Protocol):
    async def publish(self, envelope: EventEnvelope) -> None: ...


class InMemoryPublisher:
    def __init__(self) -> None:
        self.published: list[EventEnvelope] = []
        self._subscribers: list[Subscriber] = []

    def subscribe(self, handler: Subscriber) -> None:
        if handler not in self._subscribers:
            self._subscribers.append(handler)

    async def publish(self, envelope: EventEnvelope) -> None:
        self.published.append(envelope)
        # In-process bus: deliver to subscribers (real-time engine) synchronously.
        for handler in list(self._subscribers):
            await handler(envelope)

    def reset(self) -> None:
        self.published.clear()
        self._subscribers.clear()


class KafkaPublisher:  # pragma: no cover - exercised only with a live broker
    _producer = None

    async def _get(self):
        if KafkaPublisher._producer is None:
            from aiokafka import AIOKafkaProducer

            KafkaPublisher._producer = AIOKafkaProducer(
                bootstrap_servers=settings.kafka_bootstrap_servers
            )
            await KafkaPublisher._producer.start()
        return KafkaPublisher._producer

    async def publish(self, envelope: EventEnvelope) -> None:
        import json

        producer = await self._get()
        await producer.send_and_wait(
            envelope.topic,
            key=envelope.aggregate_id.encode(),
            value=json.dumps(envelope.model_dump(mode="json")).encode(),
        )


_publisher: EventPublisher | None = None


def get_publisher() -> EventPublisher:
    global _publisher
    if _publisher is None:
        if settings.events_backend == "kafka" and not settings.is_test:
            _publisher = KafkaPublisher()
        else:
            _publisher = InMemoryPublisher()
    return _publisher


def reset_publisher() -> None:
    """Test hook — drop the singleton so each test starts with a clean bus."""
    global _publisher
    _publisher = None
