"""Generic async repository with soft-delete awareness."""
from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession):
        self.session = session

    def _alive(self, stmt):
        """Filter out soft-deleted rows when the model supports it."""
        if hasattr(self.model, "deleted_at"):
            stmt = stmt.where(self.model.deleted_at.is_(None))
        return stmt

    async def get(self, id_: str) -> ModelT | None:
        stmt = self._alive(select(self.model).where(self.model.id == id_))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def add(self, obj: ModelT) -> ModelT:
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def list(self, *, offset: int = 0, limit: int = 20) -> list[ModelT]:
        stmt = self._alive(select(self.model)).offset(offset).limit(limit)
        if hasattr(self.model, "created_at"):
            stmt = stmt.order_by(self.model.created_at.desc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def count(self) -> int:
        stmt = self._alive(select(func.count()).select_from(self.model))
        return (await self.session.execute(stmt)).scalar_one()

    async def soft_delete(self, obj: ModelT) -> None:
        from app.models.base import _utcnow

        if hasattr(obj, "deleted_at"):
            obj.deleted_at = _utcnow()
            await self.session.flush()
