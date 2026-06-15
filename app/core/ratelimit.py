"""Rate limiting as a FastAPI dependency (#2).

Implemented as a dependency rather than a decorator so it never interferes with
FastAPI's request-body introspection. Fixed-window counter keyed by route-name +
trusted client IP. In-memory for a single dev instance; switch to Redis (INCR/EXPIRE)
for multi-replica production. Disabled automatically under tests.

Limit strings use the ``"<count>/<period>"`` form, e.g. ``"5/minute"``.
"""
from __future__ import annotations

import time

from fastapi import Request

from app.config import settings
from app.core.exceptions import TrustLensError

_PERIODS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}


class RateLimitExceeded(TrustLensError):
    """Too many requests."""

    status_code = 429
    code = "rate_limited"


def _parse(limit: str) -> tuple[int, int]:
    count, _, period = limit.partition("/")
    return int(count), _PERIODS.get(period.strip().lower(), 60)


class _FixedWindow:
    """key -> (window_start_epoch, count). Good enough for single-instance dev."""

    def __init__(self) -> None:
        self._buckets: dict[str, tuple[float, int]] = {}

    def hit(self, key: str, max_calls: int, window: int) -> bool:
        now = time.time()
        start, count = self._buckets.get(key, (now, 0))
        if now - start >= window:
            start, count = now, 0
        count += 1
        self._buckets[key] = (start, count)
        return count <= max_calls

    def reset(self) -> None:
        self._buckets.clear()


_counter = _FixedWindow()


def reset_rate_limiter() -> None:
    """Test hook."""
    _counter.reset()


def rate_limit(name: str, limit: str):
    """Build a dependency enforcing ``limit`` for the named route group."""
    max_calls, window = _parse(limit)

    async def _dep(request: Request) -> None:
        if not settings.rate_limit_enabled or settings.is_test:
            return
        from app.dependencies import client_ip

        key = f"{name}:{client_ip(request) or 'unknown'}"
        if not _counter.hit(key, max_calls, window):
            raise RateLimitExceeded("Too many requests; slow down")

    return _dep
