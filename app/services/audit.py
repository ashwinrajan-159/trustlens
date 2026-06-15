"""Audit service — append-only WORM trail.

Every state change and PII access goes through ``record``. State snapshots are
redacted (no raw PII) before persistence. The session is flushed but committed by
the caller's unit of work so the audit entry shares the transaction it describes.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import correlation_id_ctx, get_logger
from app.models.audit_log import AuditLog
from app.models.enums import AuditAction

# Genesis hash for the very first chained entry.
_GENESIS = "0" * 64

log = get_logger(__name__)

# Keys scrubbed from before/after snapshots before they touch the DB.
_REDACT = {
    "hashed_password",
    "password",
    "value",  # extracted_entities raw value (encrypted PII)
    "raw_text",
    "pan",
    "aadhaar",
    "account_number",
}


def _redact(state: dict[str, Any] | None) -> dict[str, Any] | None:
    if not state:
        return state
    return {k: ("***REDACTED***" if k in _REDACT else v) for k, v in state.items()}


class AuditService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _latest_hash(self) -> str:
        """Most recent entry_hash, or genesis if the chain is empty.

        Note: concurrent inserts in separate uncommitted transactions can read the
        same predecessor (a fork). Acceptable for MVP tamper-evidence; a strict chain
        would serialise writes through an advisory lock / single writer.
        """
        stmt = (
            select(AuditLog.entry_hash)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(1)
        )
        latest = (await self.session.execute(stmt)).scalars().first()
        return latest or _GENESIS

    async def record(
        self,
        *,
        action: AuditAction,
        entity_type: str,
        entity_id: str | None = None,
        actor_id: str | None = None,
        before: dict | None = None,
        after: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLog:
        before_r, after_r = _redact(before), _redact(after)

        # Tamper-evidence chain: link each entry to the previous one (#7).
        prev_hash = await self._latest_hash()
        payload = json.dumps(
            {
                "actor_id": actor_id,
                "action": action.value,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "before": before_r,
                "after": after_r,
                "correlation_id": correlation_id_ctx.get(),
            },
            sort_keys=True,
            default=str,
        )
        entry_hash = hashlib.sha256((prev_hash + payload).encode()).hexdigest()

        entry = AuditLog(
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_state=before_r,
            after_state=after_r,
            ip_address=ip_address,
            user_agent=user_agent,
            correlation_id=correlation_id_ctx.get(),
            prev_hash=prev_hash,
            entry_hash=entry_hash,
        )
        self.session.add(entry)
        await self.session.flush()
        log.info(
            "audit.record",
            action=action.value,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_id=actor_id,
        )
        return entry
