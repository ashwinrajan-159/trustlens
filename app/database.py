"""Async SQLAlchemy engine + session factory.

A single ``AsyncEngine`` is created from ``settings.database_url``. The
``get_db`` dependency yields a session per request and guarantees rollback on
error and close on exit. Tests override the engine with SQLite in-memory.
"""
from __future__ import annotations

import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import settings

# ``pool_pre_ping`` avoids stale connections; SQLite (tests) ignores pool args.
_engine_kwargs: dict = {"echo": settings.db_echo, "future": True}
if not settings.database_url.startswith("sqlite"):
    _engine_kwargs["pool_pre_ping"] = True
    # Inside the Celery worker each task runs in a fresh asyncio loop via
    # ``asyncio.run()``. asyncpg pins each pooled connection to the loop that
    # created it, so reusing one across tasks raises "Future attached to a
    # different loop". NullPool opens and disposes a connection per checkout,
    # eliminating cross-loop reuse. The API (one long-lived loop) keeps pooling.
    if os.getenv("WORKER_PROCESS") == "1":
        _engine_kwargs["poolclass"] = NullPool
        _engine_kwargs.pop("pool_pre_ping", None)

engine = create_async_engine(settings.database_url, **_engine_kwargs)

SessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: one session per request, rollback on error."""
    async with SessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
