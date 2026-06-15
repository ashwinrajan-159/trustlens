"""Immutable (WORM) audit trail.

Every state change and every PII access is recorded here. The table is append-only:
the Alembic migration installs PostgreSQL rules that turn UPDATE/DELETE into no-ops
(``no_update`` / ``no_delete``), so immutability is enforced by the database itself.

``before_state`` / ``after_state`` hold redacted JSON snapshots — never raw PII.
"""
from __future__ import annotations

from sqlalchemy import JSON, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import ImmutableBase
from app.models.enums import AuditAction


class AuditLog(ImmutableBase):
    __tablename__ = "audit_logs"

    actor_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    action: Mapped[AuditAction] = mapped_column(
        SAEnum(AuditAction, native_enum=False, length=32), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)

    before_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)

    # Tamper-evidence hash chain (#7): entry_hash = sha256(prev_hash || canonical payload).
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entry_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuditLog {self.action.value} {self.entity_type}:{self.entity_id}>"
