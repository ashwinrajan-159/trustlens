"""Password hashing + JWT issue/verify.

- Passwords: Argon2id primary (``argon2-cffi``), with transparent bcrypt verification
  for any legacy hashes (#20). ``needs_rehash`` lets callers upgrade old hashes on login.
- Tokens: short-lived access + long-lived refresh, signed HS256. Each carries ``sub``
  (user id), ``role``, ``type`` (access|refresh), ``fid`` (token-family id for rotation),
  ``jti`` (unique id) and ``exp``.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from jose import JWTError, jwt

from app.config import settings
from app.core.exceptions import AuthenticationError

_argon2 = PasswordHasher()

ACCESS = "access"
REFRESH = "refresh"


def hash_password(password: str) -> str:
    return _argon2.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    # Argon2 hashes start with "$argon2"; anything else is treated as legacy bcrypt.
    if hashed.startswith("$argon2"):
        try:
            return _argon2.verify(hashed, plain)
        except (VerifyMismatchError, Exception):  # noqa: BLE001
            return False
    return _verify_bcrypt(plain, hashed)


def _verify_bcrypt(plain: str, hashed: str) -> bool:
    try:
        import bcrypt

        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:  # noqa: BLE001
        return False


def needs_rehash(hashed: str) -> bool:
    """True if the stored hash should be upgraded (legacy bcrypt or stale argon2 params)."""
    if not hashed.startswith("$argon2"):
        return True
    try:
        return _argon2.check_needs_rehash(hashed)
    except Exception:  # noqa: BLE001
        return True


def _now() -> datetime:
    return datetime.now(UTC)


def _create_token(
    subject: str, role: str, token_type: str, expires: timedelta, *, fid: str, jti: str
) -> str:
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "type": token_type,
        "fid": fid,
        "jti": jti,
        "iat": int(_now().timestamp()),
        "exp": int((_now() + expires).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(subject: str, role: str, *, fid: str, jti: str | None = None) -> str:
    return _create_token(
        subject, role, ACCESS,
        timedelta(minutes=settings.access_token_expire_minutes),
        fid=fid, jti=jti or uuid.uuid4().hex,
    )


def create_refresh_token(subject: str, role: str, *, fid: str, jti: str) -> str:
    return _create_token(
        subject, role, REFRESH,
        timedelta(days=settings.refresh_token_expire_days),
        fid=fid, jti=jti,
    )


def new_id() -> str:
    return uuid.uuid4().hex


def decode_token(token: str, *, expected_type: str | None = None) -> dict[str, Any]:
    """Decode + validate a JWT. Raises ``AuthenticationError`` on any problem."""
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
    except JWTError as exc:
        raise AuthenticationError("Invalid or expired token") from exc
    if expected_type and payload.get("type") != expected_type:
        raise AuthenticationError(f"Expected a {expected_type} token")
    if "sub" not in payload:
        raise AuthenticationError("Malformed token (no subject)")
    return payload
