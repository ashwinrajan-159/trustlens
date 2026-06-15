"""Celery application.

Dedicated CPU queue for OCR; default I/O queue for everything else; a DLQ for
poison messages. ``task_acks_late=True`` so a task is only acked after it completes,
making redelivery safe (every task is idempotent). Tasks are registered by importing
``app.tasks`` modules below.
"""
from __future__ import annotations

from celery import Celery

from app.config import settings

celery_app = Celery(
    "trustlens",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.tasks.ocr",
        "app.tasks.extraction",
        "app.tasks.fraud",
        "app.tasks.identity",
        "app.tasks.cross_document",
        "app.tasks.property",
        "app.tasks.financial",
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
    },
    task_acks_on_failure_or_timeout=True,
    result_expires=3600,
    timezone="UTC",
    enable_utc=True,
)
