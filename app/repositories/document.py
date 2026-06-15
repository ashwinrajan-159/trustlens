"""Document data access.

Checksum lookups use ordered ``limit(1)`` — never ``scalar_one_or_none`` — because
a checksum can legitimately recur across applications (same template, duplicate upload).
"""
from __future__ import annotations

from sqlalchemy import select

from app.models.document import Document
from app.repositories.base import BaseRepository


class DocumentRepository(BaseRepository[Document]):
    model = Document

    async def list_for_application(self, application_id: str) -> list[Document]:
        stmt = (
            self._alive(
                select(Document).where(Document.application_id == application_id)
            )
            .where(Document.is_current_version.is_(True))
            .order_by(Document.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def find_by_checksum(self, checksum: str) -> Document | None:
        """First match by checksum (duplicates are expected — ordered limit(1))."""
        stmt = (
            self._alive(select(Document).where(Document.checksum_sha256 == checksum))
            .order_by(Document.created_at.asc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()
