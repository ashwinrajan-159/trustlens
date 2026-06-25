"""Celery application.

Dedicated CPU queue for OCR; default I/O queue for everything else; a DLQ for
poison messages. ``task_acks_late=True`` so a task is only acked after it completes,
making redelivery safe (every task is idempotent). Tasks are registered by importing
``app.tasks`` modules below.
"""
from __future__ import annotations

from celery import Celery
from celery.signals import worker_ready

from app.config import settings

celery_app = Celery(
    "trustlens",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.tasks.ocr",
        "app.tasks.extraction",
        "app.tasks.fraud",
        "app.tasks.forensics",
        "app.tasks.identity",
        "app.tasks.cross_document",
        "app.tasks.property",
        "app.tasks.financial",
        "app.tasks.graph",
        "app.tasks.events",
        "app.tasks.learning",
    ],
)

celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    task_default_queue="default",
    task_routes={
        "app.tasks.ocr.*": {"queue": "ocr"},
        "app.tasks.extraction.*": {"queue": "default"},
        "app.tasks.fraud.*": {"queue": "default"},
        "app.tasks.identity.*": {"queue": "default"},
        "app.tasks.cross_document.*": {"queue": "default"},
        "app.tasks.property.*": {"queue": "default"},
        "app.tasks.financial.*": {"queue": "default"},
        "app.tasks.graph.*": {"queue": "default"},
        "app.tasks.events.*": {"queue": "default"},
        "app.tasks.learning.*": {"queue": "default"},
    },
    task_acks_on_failure_or_timeout=True,
    result_expires=3600,
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        # Durability backstop: re-publish any stuck outbox events every minute.
        "replay-pending-events": {
            "task": "app.tasks.events.replay_pending_events",
            "schedule": 60.0,
        },
        # Drift backstop: nightly rebuild of knowledge-base projections from the
        # immutable record (pattern counters + per-signal precision).
        "recompute-knowledge-base": {
            "task": "app.tasks.learning.recompute_knowledge_base",
            "schedule": 24 * 60 * 60.0,
        },
    },
)


@worker_ready.connect
def _init_realtime(**_):  # pragma: no cover - runs only inside a live worker
    """Subscribe the real-time engine + install the alert escalation hook so risk
    events emitted by pipeline tasks turn into fraud alerts inside the worker too."""
    from app.events.consumer import get_realtime_engine
    from app.services.alerting import install_escalation_hook

    get_realtime_engine()
    install_escalation_hook()
