"""Auth endpoints: register, login, refresh, logout, me, MFA, consent withdrawal."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.ratelimit import rate_limit
from app.database import get_db
from app.dependencies import (
    CurrentUser,
    client_ip,
    get_current_db_user,
    get_current_user,
)
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    MFAEnrollResponse,
    MFAVerifyRequest,
    RefreshRequest,
    RegisterResponse,
    TokenPair,
)
from app.schemas.common import ERROR_RESPONSES, MessageResponse
from app.schemas.user import UserCreate, UserPublic
from app.services.auth import AuthService
from app.services.user import UserService

router = APIRouter(prefix="/auth", tags=["auth"], responses=ERROR_RESPONSES)


@router.post(
    "/register", response_model=RegisterResponse, status_code=201,
    dependencies=[Depends(rate_limit("auth_register", settings.rate_limit_auth))],
)
async def register(
    data: UserCreate, request: Request, db: AsyncSession = Depends(get_db)
) -> RegisterResponse:
    user, tokens = await AuthService(db).register(data, ip=client_ip(request))
    return RegisterResponse(user=UserPublic.model_validate(user), tokens=tokens)


@router.post(
    "/login", response_model=TokenPair,
    dependencies=[Depends(rate_limit("auth_login", settings.rate_limit_login))],
)
async def login(
    data: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> TokenPair:
    _, tokens = await AuthService(db).login(
        data.email, data.password, mfa_code=data.mfa_code, ip=client_ip(request)
    )
    return tokens


@router.post(
    "/refresh", response_model=TokenPair,
    dependencies=[Depends(rate_limit("auth_refresh", settings.rate_limit_auth))],
)
async def refresh(
    data: RefreshRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> TokenPair:
    return await AuthService(db).refresh(data.refresh_token)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    data: LogoutRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> MessageResponse:
    await AuthService(db).logout(data.refresh_token)
    return MessageResponse(message="Logged out")


@router.get("/me", response_model=UserPublic)
async def me(user=Depends(get_current_db_user)) -> UserPublic:
    return UserPublic.model_validate(user)


# ── MFA (TOTP) ──
@router.post("/mfa/enroll", response_model=MFAEnrollResponse)
async def mfa_enroll(
    user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> MFAEnrollResponse:
    secret, uri = await UserService(db).begin_mfa_enrollment(user.id)
    return MFAEnrollResponse(secret=secret, provisioning_uri=uri)


@router.post("/mfa/verify", response_model=MessageResponse)
async def mfa_verify(
    data: MFAVerifyRequest,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await UserService(db).confirm_mfa_enrollment(user.id, data.code, ip=client_ip(request))
    return MessageResponse(message="MFA enabled")


# ── DPDP consent withdrawal (#24) ──
@router.post("/consent/withdraw", response_model=MessageResponse)
async def withdraw_consent(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await UserService(db).withdraw_consent(user.id, ip=client_ip(request))
    return MessageResponse(message="Consent withdrawal recorded")
