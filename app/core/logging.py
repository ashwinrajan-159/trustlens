"""Structured logging (structlog) with correlation-id propagation.

ZERO-PII rule: never log raw PII or full document text. Logs carry only IDs,
a ``correlation_id`` and a ``user_id`` at most. A processor strips a denylist of
sensitive keys defensively in case a caller forgets.
"""
from __future__ import annotations

import logging
from contextvars import ContextVar

import structlog

# Request-scoped correlation id, set by middleware.
correlation_id_ctx: ContextVar[str | None] = ContextVar("correlation_id", default=None)

# Defensive denylist — these keys are redacted from every event.
_SENSITIVE_KEYS = {
    "password",
    "hashed_password",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "pan",
    "aadhaar",
    "account_number",
    "raw_text",
    "fernet_key",
    "jwt_secret_key",
    "secret",
}


def _add_correlation_id(_logger, _method, event_dict: dict) -> dict:
    cid = correlation_id_ctx.get()
    if cid:
        event_dict.setdefault("correlation_id", cid)
    return event_dict


def _redact_sensitive(_logger, _method, event_dict: dict) -> dict:
    for key in list(event_dict.keys()):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = "***REDACTED***"
    return event_dict


def configure_logging(*, debug: bool = False, json_logs: bool = True) -> None:
    """Configure structlog once at startup."""
    renderer = (
        structlog.dev.ConsoleRenderer()
        if debug and not json_logs
        else structlog.processors.JSONRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _add_correlation_id,
            _redact_sensitive,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if debug else logging.INFO
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
