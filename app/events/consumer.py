"""Consumers + real-time risk engine (Phase 8).

The real-time engine subscribes to the event bus and reacts to high-severity events
(CRITICAL/HIGH risk, fraud rings) sub-second. It is **idempotent** on ``event_id`` so a
redelivered Kafka message (or a replayed outbox row) is handled at most once.

Escalation (turning an event into a fraud alert / investigation case) is a hook that
Phase 10 (alerting + case management) fills in. For now it records the intent so the
behaviour is observable and testable without those tables.

``run_kafka_consumer`` is the production consumer loop (lazy aiokafka import); the
in-process ``InMemoryPublisher`` path exercises the same handler in dev/test.
"""
from __future__ import annotations

from app.core.logging import get_logger
from app.events.publisher import InMemoryPublisher, get_publisher
from app.events.schemas import EventEnvelope
from app.models.enums import EventType

log = get_logger(__name__)

# Escalation hook — Phase 10 replaces this with alert/case creation.
EscalationHook = None  # type: ignore[assignment]


class RealTimeRiskEngine:
    """Stateless-ish reactor; idempotency set is per-process (Phase 10 persists it)."""

    HIGH_RISK_TIERS = {"HIGH", "CRITICAL"}
    ESCALATING_EVENTS = {EventType.RISK_CALCULATED, EventType.FRAUD_RING_DETECTED}

    def __init__(self) -> None:
        self._processed: set[str] = set()
        self.escalations: list[EventEnvelope] = []  # observable for tests/ops

    async def handle(self, envelope: EventEnvelope) -> None:
        if envelope.event_id in self._processed:
            return  # idempotent: at-most-once effects
        self._processed.add(envelope.event_id)

        if envelope.event_type not in self.ESCALATING_EVENTS:
            return
        if envelope.event_type == EventType.RISK_CALCULATED:
            tier = (envelope.payload or {}).get("tier")
            if tier not in self.HIGH_RISK_TIERS:
                return
        await self._escalate(envelope)

    async def _escalate(self, envelope: EventEnvelope) -> None:
        self.escalations.append(envelope)
        log.info(
            "realtime.escalation",
            event_type=envelope.event_type.value,
            application_id=envelope.aggregate_id,
            correlation_id=envelope.correlation_id,
        )
        # ── Phase 10 hook: create a FraudAlert / InvestigationCase here. ──
        if EscalationHook is not None:  # pragma: no cover - wired in Phase 10
            await EscalationHook(envelope)

    def reset(self) -> None:
        self._processed.clear()
        self.escalations.clear()


_engine: RealTimeRiskEngine | None = None


def get_realtime_engine() -> RealTimeRiskEngine:
    """Singleton engine, auto-subscribed to the in-process bus when backend is memory."""
    global _engine
    if _engine is None:
        _engine = RealTimeRiskEngine()
        publisher = get_publisher()
        if isinstance(publisher, InMemoryPublisher):
            publisher.subscribe(_engine.handle)
    return _engine


def reset_realtime_engine() -> None:
    """Test hook."""
    global _engine
    if _engine is not None:
        _engine.reset()
    _engine = None


async def run_kafka_consumer(topics: list[str]) -> None:  # pragma: no cover - needs broker
    """Production consumer loop: deliver each message to the real-time engine.
    DLQ routing on repeated failure is handled by the deployment's consumer supervisor."""
    import json

    from aiokafka import AIOKafkaConsumer

    from app.config import settings

    engine = get_realtime_engine()
    consumer = AIOKafkaConsumer(
        *topics,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        enable_auto_commit=True,
        group_id="trustlens-realtime",
    )
    await consumer.start()
    try:
        async for msg in consumer:
            data = json.loads(msg.value.decode())
            await engine.handle(EventEnvelope(**data))
    finally:
        await consumer.stop()
