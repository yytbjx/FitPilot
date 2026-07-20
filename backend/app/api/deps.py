"""API 依赖：请求 ID、鉴权、统一响应。"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import JWTError, decode_access_token
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import ApiResponse, ErrorBody

_bearer = HTTPBearer(auto_error=False)


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:12]}"


def get_request_id(request: Request) -> str:
    return getattr(request.state, "request_id", new_request_id())


def ok(request_id: str, data: Any) -> dict[str, Any]:
    return ApiResponse(request_id=request_id, status="success", data=data).model_dump()


def fail(
    request_id: str, code: str, message: str, details: dict | None = None
) -> dict[str, Any]:
    return ApiResponse(
        request_id=request_id,
        status="error",
        error=ErrorBody(code=code, message=message, details=details),
    ).model_dump()


async def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """解析 Bearer JWT，返回当前用户。"""
    rid = get_request_id(request)
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=fail(rid, "UNAUTHORIZED", "缺少访问令牌"),
        )
    try:
        payload = decode_access_token(creds.credentials)
        user_id = int(payload.get("sub", "0"))
    except (JWTError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=fail(rid, "INVALID_TOKEN", "令牌无效或已过期"),
        ) from None

    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=fail(rid, "USER_NOT_FOUND", "用户不存在"),
        )
    return user


def require_role(*roles: str):
    """RBAC：要求用户具备指定角色之一（admin 可访问一切）。"""

    async def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role == "admin" or user.role in roles:
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "权限不足"},
        )

    return _dep
