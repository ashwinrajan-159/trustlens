"""User self-service: MFA enrollment (#25) and DPDP consent withdrawal (#24)."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.enums import AuditAction
from app.repositories.user import UserRepository
from app.services import mfa
from app.services.audit import AuditService

log = get_logger(__name__)


class UserService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.users = UserRepository(session)
        self.audit = AuditService(session)

    async def begin_mfa_enrollment(self, user_id: str) -> tuple[str, str]:
        user = await self.users.get(user_id)
        if not user:
            raise NotFoundError("User not found")
        secret = mfa.generate_secret()
        user.mfa_secret = secret
        user.mfa_enabled = False  # not active until verified
        await self.session.commit()
        return secret, mfa.provisioning_uri(secret, user.email)

    async def confirm_mfa_enrollment(self, user_id: str, code: str, *, ip: str | None = None) -> None:
        user = await self.users.get(user_id)
        if not user or not user.mfa_secret:
            raise ValidationError("Start MFA enrollment first")
        if not mfa.verify_totp(user.mfa_secret, code):
            raise ValidationError("Invalid MFA code")
        user.mfa_enabled = True
        await self.audit.record(
            action=AuditAction.UPDATE, entity_type="user", entity_id=user.id,
            actor_id=user.id, after={"mfa_enabled": True}, ip_address=ip,
        )
        await self.session.commit()
        log.info("user.mfa_enabled", user_id=user.id)

    async def withdraw_consent(self, user_id: str, *, ip: str | None = None) -> None:
        """DPDP right to withdraw consent. Records the timestamp + audit entry; the
        erasure workflow (Phase 14) acts on this while preserving the audit trail."""
        user = await self.users.get(user_id)
        if not user:
            raise NotFoundError("User not found")
        user.data_consent_withdrawn_at = datetime.now(UTC)
        await self.audit.record(
            action=AuditAction.UPDATE, entity_type="user", entity_id=user.id,
            actor_id=user.id, after={"data_consent_withdrawn": True}, ip_address=ip,
        )
        await self.session.commit()
        log.info("user.consent_withdrawn", user_id=user.id)
