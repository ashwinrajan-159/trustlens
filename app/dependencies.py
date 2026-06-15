"""FastAPI dependency wiring: DB session, current user, RBAC guards, services.

The authenticated principal is a lightweight ``CurrentUser`` decoded from the JWT
plus a DB lookup (to honour deactivation/soft-delete without waiting for token
expiry). Role guards are dependency factories.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.security import ACCESS, decode_token
from app.database import get_db
from app.models.enums import ANALYST_ROLES, SENIOR_ROLES, UserRole
from app.repositories.user import UserRepository
from app.services.storage import StorageService

_bearer = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    id: str
    email: str
    role: UserRole


def _is_trusted_proxy(peer: str | None) -> bool:
    if not peer or not settings.trusted_proxies:
        return False
    try:
        addr = ipaddress.ip_address(peer)
    except ValueError:
        return False
    for entry in settings.trusted_proxies:
        try:
            if "/" in entry:
                if addr in ipaddress.ip_network(entry, strict=False):
                    return True
            elif addr == ipaddress.ip_address(entry):
                return True
        except ValueError:
            continue
    return False


def client_ip(request: Request) -> str | None:
    """Real client IP. X-Forwarded-For is honoured ONLY when the direct peer is a
    configured trusted proxy (#6); otherwise it is attacker-controlled and ignored."""
    peer = request.client.host if request.client else None
    if _is_trusted_proxy(peer):
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return peer


async def get_current_db_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
):
    """Resolve the authenticated ORM ``User`` (honours deactivation/soft-delete)."""
    if credentials is None:
        raise AuthenticationError("Missing bearer token")
    payload = decode_token(credentials.credentials, expected_type=ACCESS)
    user = await UserRepository(db).get(payload["sub"])
    if not user or not user.is_active:
        raise AuthenticationError("User not found or inactive")
    return user


async def get_current_user(user=Depends(get_current_db_user)) -> CurrentUser:
    return CurrentUser(id=user.id, email=user.email, role=user.role)


def require_roles(*roles: UserRole):
    allowed = set(roles)

    async def _guard(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed:
            raise AuthorizationError("Insufficient privileges for this action")
        return user

    return _guard


# Convenience guards.
require_analyst = require_roles(*ANALYST_ROLES)
require_senior = require_roles(*SENIOR_ROLES)


# Storage service is stateless/session-less — a single shared instance is fine.
_storage_singleton = StorageService()


def get_storage() -> StorageService:
    return _storage_singleton
