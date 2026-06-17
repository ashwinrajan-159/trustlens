"""Versioned, PII-free domain-event envelope + typed builders (Phase 8).

Every event is an ``EventEnvelope``: a stable header (id/type/version/correlation) plus a
``payload`` that contains ONLY identifiers and safe scalars (scores, tiers, counts,
severities). Builders are the single way to construct events, so PII can't leak in by
accident. ``occurred_at`` is injected by the caller (the worker stamps it) to keep this
module pure/deterministic.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.enums import TOPIC_MAP, EventType


class EventEnvelope(BaseModel):
    event_id: str
    event_type: EventType
    event_version: int = 1
    aggregate_type: str
    aggregate_id: str
    correlation_id: str | None = None
    occurred_at: str | None = None
    payload: dict = Field(default_factory=dict)

    @property
    def topic(self) -> str:
        return TOPIC_MAP[self.event_type]


def _env(event_id, event_type, aggregate_type, aggregate_id, correlation_id, payload, version=1):
    return EventEnvelope(
        event_id=event_id,
        event_type=event_type,
        event_version=version,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        correlation_id=correlation_id,
        payload=payload,
    )


# ── Builders (IDs + safe scalars only) ──

def application_created(event_id, application_id, *, applicant_id, loan_type, correlation_id=None):
    return _env(event_id, EventType.APPLICATION_CREATED, "application", application_id,
                correlation_id, {"applicant_id": applicant_id, "loan_type": loan_type})


def application_submitted(event_id, application_id, *, correlation_id=None):
    return _env(event_id, EventType.APPLICATION_SUBMITTED, "application", application_id,
                correlation_id, {})


def document_uploaded(event_id, document_id, *, application_id, document_type, correlation_id=None):
    return _env(event_id, EventType.DOCUMENT_UPLOADED, "document", document_id,
                correlation_id, {"application_id": application_id, "document_type": document_type})


def risk_calculated(event_id, application_id, *, score, tier, signal_count, correlation_id=None):
    return _env(event_id, EventType.RISK_CALCULATED, "application", application_id,
                correlation_id, {"score": score, "tier": tier, "signal_count": signal_count})


def analyst_decision_made(event_id, application_id, *, decision, decided_by, correlation_id=None):
    return _env(event_id, EventType.ANALYST_DECISION_MADE, "application", application_id,
                correlation_id, {"decision": decision, "decided_by": decided_by})


def identity_flagged(event_id, application_id, *, indicators, correlation_id=None):
    return _env(event_id, EventType.IDENTITY_FLAGGED, "application", application_id,
                correlation_id, {"indicators": indicators})


def property_flagged(event_id, application_id, *, reason, correlation_id=None):
    return _env(event_id, EventType.PROPERTY_FLAGGED, "application", application_id,
                correlation_id, {"reason": reason})


def fraud_ring_detected(event_id, application_id, *, ring_size, application_ids, correlation_id=None):
    return _env(event_id, EventType.FRAUD_RING_DETECTED, "application", application_id,
                correlation_id, {"ring_size": ring_size, "application_ids": application_ids})


def model_prediction_generated(event_id, application_id, *, probability, tier, model_id, correlation_id=None):
    return _env(event_id, EventType.MODEL_PREDICTION_GENERATED, "application", application_id,
                correlation_id, {"probability": probability, "tier": tier, "model_id": model_id})


def fraud_alert_generated(event_id, alert_id, *, application_id, alert_type, severity, correlation_id=None):
    return _env(event_id, EventType.FRAUD_ALERT_GENERATED, "alert", alert_id,
                correlation_id, {"application_id": application_id, "alert_type": alert_type, "severity": severity})


def case_created(event_id, case_id, *, case_type, priority, correlation_id=None):
    return _env(event_id, EventType.CASE_CREATED, "case", case_id,
                correlation_id, {"case_type": case_type, "priority": priority})


def case_closed(event_id, case_id, *, outcome, correlation_id=None):
    return _env(event_id, EventType.CASE_CLOSED, "case", case_id, correlation_id, {"outcome": outcome})
