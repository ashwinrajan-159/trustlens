"""Declarative base + common mixins.

- ``Base`` — the shared declarative base.
- ``UUIDMixin`` — UUID string PK (portable across Postgres + SQLite tests).
- ``TimestampMixin`` — ``created_at`` / ``updated_at``.
- ``SoftDeleteMixin`` — ``deleted_at`` (soft delete everywhere except audit).
- ``ImmutableBase`` — for write-once tables (audit_logs); no soft delete, no updated_at.

UUIDs are stored as 36-char strings rather than the PG ``UUID`` type so the exact
same models run under SQLite in tests. In a pure-Postgres deployment this could be
swapped for native ``UUID`` without changing call sites.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class UUIDMixin:
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_uuid, index=True
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class ImmutableBase(UUIDMixin, Base):
    """Base for write-once tables. Only ``created_at`` — no update/delete columns.

    DB-level ``no_update`` / ``no_delete`` rules are added in the migration so the
    immutability is enforced by Postgres, not just by application convention.
    """

    __abstract__ = True

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False
    )
