"""Auth request/response schemas."""
from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.schemas.user import UserPublic


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    mfa_code: str | None = Field(default=None, min_length=6, max_length=8)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


# ── MFA (TOTP) ──
class MFAEnrollResponse(BaseModel):
    secret: str
    provisioning_uri: str  # otpauth:// — render as a QR for the authenticator app


class MFAVerifyRequest(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class RegisterResponse(BaseModel):
    user: UserPublic
    tokens: TokenPair
