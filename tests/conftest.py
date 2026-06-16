"""Test fixtures: SQLite in-memory DB + dependency overrides (no Postgres/MinIO).

Environment is set BEFORE any app import so cached settings pick up test values.
"""
from __future__ import annotations

import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-production-use-only")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
# Deterministic Fernet key so encryption round-trips within a test run.
os.environ.setdefault("FERNET_KEY", "zXqQ4n8s2rT6vY9bB1dD3fF5hH7jJ0kK2lL4mM6nN8o=")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database import get_db  # noqa: E402
from app.dependencies import get_storage  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402

# Single shared in-memory connection (StaticPool) so schema persists across sessions.
_engine = create_async_engine(
    "sqlite+aiosqlite://",
    poolclass=StaticPool,
    connect_args={"check_same_thread": False},
)
_SessionFactory = async_sessionmaker(bind=_engine, class_=AsyncSession, expire_on_commit=False)


class FakeStorage:
    """In-memory stand-in for MinIO/S3 so document tests need no real bucket."""

    def __init__(self) -> None:
        self._bucket = "test-bucket"
        self.objects: dict[str, bytes] = {}

    @staticmethod
    def build_key(application_id: str, document_id: str, filename: str) -> str:
        from app.services.storage import StorageService

        return StorageService.build_key(application_id, document_id, filename)

    async def ensure_bucket(self) -> None:  # pragma: no cover
        return None

    async def upload(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = data

    async def download(self, key: str) -> bytes:
        return self.objects[key]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    async def presigned_download_url(self, key: str) -> str:
        return f"https://fake-storage.local/{key}?signed=1"


@pytest_asyncio.fixture(autouse=True)
async def _setup_db():
    from app.core.ratelimit import reset_rate_limiter
    from app.core.token_store import reset_token_store
    from app.events.consumer import get_realtime_engine, reset_realtime_engine
    from app.events.publisher import reset_publisher
    from app.services.ml import reset_model_cache
    from app.services.ocr import set_engine_override

    reset_token_store()
    reset_rate_limiter()
    set_engine_override(None)
    reset_model_cache()
    # Fresh in-process event bus per test, with the real-time engine subscribed.
    reset_realtime_engine()
    reset_publisher()
    get_realtime_engine()
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    async def _override_get_db():
        async with _SessionFactory() as session:
            try:
                yield session
            finally:
                await session.close()

    fake_storage = FakeStorage()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_storage] = lambda: fake_storage
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.fake_storage = fake_storage  # exposed for assertions
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def anyio_backend():
    return "asyncio"
