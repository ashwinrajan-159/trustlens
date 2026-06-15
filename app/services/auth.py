"""Authentication service: register, login, refresh (rotating), logout.

Refresh tokens are rotated on every use and tracked per family in the TokenStore so
that logout works and a replayed (stolen-then-rotated) refresh token revokes the whole
family (#3). Legacy password hashes are transparently upgraded on successful login (#20).
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import AuthenticationError, ConflictError
from app.core.logging import get_logger
from app.core.security import (
    REFRESH,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    needs_rehash,
    new_id,
    verify_password,
)
from app.core.token_store import get_token_store
from app.models.enums import AuditAction, UserRole
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.auth import TokenPair
from app.schemas.user import UserCreate
from app.services.audit import AuditService

log = get_logger(__name__)


class AuthService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.users = UserRepository(session)
        self.audit = AuditService(session)
        self.tokens = get_token_store()

    async def _issue(self, user: User) -> TokenPair:
        """Open a new token family (login/register)."""
        fid = new_id()
        refresh_jti = new_id()
        ttl = settings.refresh_token_expire_days * 86400
        await self.tokens.set_current(fid, refresh_jti, ttl)
        return TokenPair(
            access_token=create_access_token(user.id, user.role.value, fid=fid),
            refresh_token=create_refresh_token(user.id, user.role.value, fid=fid, jti=refresh_jti),
        )

    async def register(self, data: UserCreate, *, ip: str | None = None) -> tuple[User, TokenPair]:
        existing = await self.users.get_by_email(data.email)
        if existing:
            raise ConflictError("An account with this email already exists")

        user = User(
            email=data.email.lower(),
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
            role=UserRole.CUSTOMER,
            data_consent_given_at=(
                datetime.now(UTC) if data.data_consent_given else None
            ),
        )
        await self.users.add(user)
        await self.audit.record(
            action=AuditAction.CREATE, entity_type="user", entity_id=user.id,
            actor_id=user.id, after={"email": user.email, "role": user.role.value}, ip_address=ip,
        )
        await self.session.commit()
        log.info("auth.register", user_id=user.id)
        return user, await self._issue(user)

    async def login(
        self, email: str, password: str, *, mfa_code: str | None = None, ip: str | None = None
    ) -> tuple[User, TokenPair]:
        user = await self.users.get_by_email(email)
        # Verify even when user missing to reduce timing signal.
        if not user or not verify_password(password, user.hashed_password):
            raise AuthenticationError("Invalid email or password")
        if not user.is_active:
            raise AuthenticationError("Account is disabled")

        # MFA gate for privileged roles (#25). Customers are exempt.
        if getattr(user, "mfa_enabled", False):
            from app.services.mfa import verify_totp

            if not mfa_code or not verify_totp(user.mfa_secret, mfa_code):
                raise AuthenticationError("Valid MFA code required")

        # Opportunistically upgrade legacy/stale password hashes.
        if needs_rehash(user.hashed_password):
            user.hashed_password = hash_password(password)

        await self.audit.record(
            action=AuditAction.LOGIN, entity_type="user", entity_id=user.id,
            actor_id=user.id, ip_address=ip,
        )
        await self.session.commit()
        log.info("auth.login", user_id=user.id)
        return user, await self._issue(user)

    async def refresh(self, refresh_token: str) -> TokenPair:
        payload = decode_token(refresh_token, expected_type=REFRESH)
        fid, jti = payload.get("fid"), payload.get("jti")
        if not fid or not jti:
            raise AuthenticationError("Malformed refresh token")

        current = await self.tokens.get_current(fid)
        if current is None:
            raise AuthenticationError("Session has been revoked")
        if current != jti:
            # Reuse of a rotated token → likely theft. Revoke the whole family.
            await self.tokens.revoke(fid)
            log.warning("auth.refresh_reuse_detected", fid=fid)
            raise AuthenticationError("Refresh token reuse detected; session revoked")

        user = await self.users.get(payload["sub"])
        if not user or not user.is_active:
            await self.tokens.revoke(fid)
            raise AuthenticationError("Invalid refresh token")

        # Rotate within the same family.
        new_jti = new_id()
        ttl = settings.refresh_token_expire_days * 86400
        await self.tokens.set_current(fid, new_jti, ttl)
        return TokenPair(
            access_token=create_access_token(user.id, user.role.value, fid=fid),
            refresh_token=create_refresh_token(user.id, user.role.value, fid=fid, jti=new_jti),
        )

    async def logout(self, refresh_token: str) -> None:
        """Revoke the token family. Existing short-lived access tokens expire naturally."""
        try:
            payload = decode_token(refresh_token, expected_type=REFRESH)
        except AuthenticationError:
            return  # already invalid — nothing to do
        fid = payload.get("fid")
        if fid:
            await self.tokens.revoke(fid)
            log.info("auth.logout", fid=fid)
