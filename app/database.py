"""Async SQLAlchemy engine + session factory.

A single ``AsyncEngine`` is created from ``settings.database_url``. The
``get_db`` dependency yields a session per request and guarantees rollback on
error and close on exit. Tests override the engine with SQLite in-memory.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

# ``pool_pre_ping`` avoids stale connections; SQLite (tests) ignores pool args.
_engine_kwargs: dict = {"echo": settings.db_echo, "future": True}
if not settings.database_url.startswith("sqlite"):
    _engine_kwargs["pool_pre_ping"] = True

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
