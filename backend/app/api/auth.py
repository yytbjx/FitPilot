"""注册 / 登录 / Refresh Token。"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import fail, get_current_user, get_request_id, ok
from app.core.rate_limit import auth_rate_limit, limiter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_refresh_token,
    refresh_token_expires_at,
    verify_password,
)
from app.db.session import get_db
from app.models.auth_token import RefreshToken
from app.models.user import User, UserProfile
from app.schemas.auth_biz import LoginRequest, RefreshRequest, RegisterRequest

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_payload(user: User, access: str, refresh: str | None = None) -> dict:
    data = {
        "access_token": access,
        "token_type": "bearer",
        "user_id": user.id,
        "email": user.email,
        "role": user.role,
    }
    if refresh:
        data["refresh_token"] = refresh
    return data


async def _issue_tokens(db: AsyncSession, user: User) -> tuple[str, str]:
    access = create_access_token(user.id, {"email": user.email, "role": user.role})
    raw_refresh = create_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(raw_refresh),
            expires_at=refresh_token_expires_at(),
            revoked=False,
        )
    )
    await db.flush()
    return access, raw_refresh


@router.post("/register")
@limiter.limit(auth_rate_limit)
async def register(
    body: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    rid = get_request_id(request)
    email = body.email.lower().strip()
    exists = await db.scalar(select(User).where(User.email == email))
    if exists:
        return JSONResponse(
            status_code=409,
            content=fail(rid, "EMAIL_EXISTS", "邮箱已注册"),
        )
    user = User(email=email, hashed_password=hash_password(body.password), role="user")
    db.add(user)
    await db.flush()
    db.add(UserProfile(user_id=user.id, display_name=email.split("@")[0]))
    access, refresh = await _issue_tokens(db, user)
    await db.commit()
    await db.refresh(user)
    return JSONResponse(ok(rid, _token_payload(user, access, refresh)))


@router.post("/login")
@limiter.limit(auth_rate_limit)
async def login(
    body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    rid = get_request_id(request)
    email = body.email.lower().strip()
    user = await db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(body.password, user.hashed_password):
        return JSONResponse(
            status_code=401,
            content=fail(rid, "INVALID_CREDENTIALS", "邮箱或密码错误"),
        )
    access, refresh = await _issue_tokens(db, user)
    await db.commit()
    return JSONResponse(ok(rid, _token_payload(user, access, refresh)))


@router.post("/refresh")
async def refresh_token(
    body: RefreshRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    rid = get_request_id(request)
    token_hash = hash_refresh_token(body.refresh_token)
    row = await db.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked.is_(False),
        )
    )
    if not row or row.expires_at < datetime.now(UTC):
        return JSONResponse(status_code=401, content=fail(rid, "INVALID_REFRESH", "Refresh Token 无效"))
    user = await db.get(User, row.user_id)
    if not user:
        return JSONResponse(status_code=401, content=fail(rid, "USER_NOT_FOUND", "用户不存在"))
    row.revoked = True
    access, new_refresh = await _issue_tokens(db, user)
    await db.commit()
    return JSONResponse(ok(rid, _token_payload(user, access, new_refresh)))


@router.post("/logout")
async def logout(
    body: RefreshRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rid = get_request_id(request)
    token_hash = hash_refresh_token(body.refresh_token)
    row = await db.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.user_id == user.id,
        )
    )
    if row:
        row.revoked = True
        await db.commit()
    return JSONResponse(ok(rid, {"logged_out": True}))
