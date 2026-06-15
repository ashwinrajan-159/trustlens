"""Refresh-token family store for rotation + revocation (#3).

Each login/register opens a token *family* (``fid``). The store holds the single
currently-valid refresh ``jti`` for that family. On refresh we rotate (new jti) and
on logout we revoke. Presenting a refresh token whose jti is no longer current means
either a stale token or a replay of a stolen-then-rotated token → we revoke the whole
family (defence against refresh-token theft).

Backends:
- ``InMemoryTokenStore`` — dev/test default (single process).
- ``RedisTokenStore`` — production (``use_redis_token_store=True``); survives restarts
  and is shared across API replicas. TTL matches the refresh-token lifetime.
"""
from __future__ import annotations

from typing import Protocol

from app.config import settings


class TokenStore(Protocol):
    async def set_current(self, fid: str, jti: str, ttl_seconds: int) -> None: ...
    async def get_current(self, fid: str) -> str | None: ...
    async def revoke(self, fid: str) -> None: ...


class InMemoryTokenStore:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    async def set_current(self, fid: str, jti: str, ttl_seconds: int) -> None:
        self._data[fid] = jti

    async def get_current(self, fid: str) -> str | None:
        return self._data.get(fid)

    async def revoke(self, fid: str) -> None:
        self._data.pop(fid, None)


class RedisTokenStore:
    _PREFIX = "trustlens:refresh:"

    def __init__(self, url: str) -> None:
        # Imported lazily so dev/test never need redis installed/reachable.
        import redis.asyncio as aioredis

        self._redis = aioredis.from_url(url, decode_responses=True)

    async def set_current(self, fid: str, jti: str, ttl_seconds: int) -> None:
        await self._redis.set(self._PREFIX + fid, jti, ex=ttl_seconds)

    async def get_current(self, fid: str) -> str | None:
        return await self._redis.get(self._PREFIX + fid)

    async def revoke(self, fid: str) -> None:
        await self._redis.delete(self._PREFIX + fid)


_store: TokenStore | None = None


def get_token_store() -> TokenStore:
    global _store
    if _store is None:
        if settings.use_redis_token_store and not settings.is_test:
            _store = RedisTokenStore(settings.redis_url)
        else:
            _store = InMemoryTokenStore()
    return _store


def reset_token_store() -> None:
    """Test hook — drop the singleton so each test starts clean."""
    global _store
    _store = None
