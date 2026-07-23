"""受控记忆 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.memory import delete_user_memory, list_user_memories, propose_user_memory
from app.api.deps import fail, get_current_user, get_request_id, ok
from app.application.memories import confirm_memory_use_case
from app.db.session import get_db
from app.models.user import User

router = APIRouter(prefix="/memories", tags=["memories"])


class ProposeMemoryRequest(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    value: dict | str | int | float | bool
    source: str = "user"
    confidence: float = 0.9
    notes: str | None = None


class ConfirmMemoryRequest(BaseModel):
    apply_to_profile: bool = True


@router.get("")
async def list_memories(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    confirmed_only: bool = Query(False),
) -> JSONResponse:
    rid = get_request_id(request)
    items = await list_user_memories(db, user_id=user.id, confirmed_only=confirmed_only)
    return JSONResponse(ok(rid, {"items": items}))


@router.post("")
async def propose_memory(
    body: ProposeMemoryRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rid = get_request_id(request)
    row = await propose_user_memory(
        db,
        user_id=user.id,
        key=body.key,
        value=body.value,
        source=body.source,
        confidence=body.confidence,
        notes=body.notes,
    )
    if not row:
        return JSONResponse(status_code=400, content=fail(rid, "INVALID_KEY", "不支持的记忆键"))
    return JSONResponse(
        ok(
            rid,
            {
                "id": row.id,
                "key": row.key,
                "confirmed": row.confirmed,
                "requires_confirmation": row.requires_confirmation,
            },
        )
    )


@router.post("/{memory_id}/confirm")
async def confirm_memory(
    memory_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    body: ConfirmMemoryRequest = ConfirmMemoryRequest(),
) -> JSONResponse:
    rid = get_request_id(request)
    data = await confirm_memory_use_case(
        db,
        user_id=user.id,
        memory_id=memory_id,
        apply_to_profile=body.apply_to_profile,
        request_id=rid,
    )
    if data.get("error") == "NOT_FOUND":
        return JSONResponse(status_code=404, content=fail(rid, "NOT_FOUND", "记忆不存在"))
    return JSONResponse(ok(rid, data))


@router.delete("/{memory_id}")
async def remove_memory(
    memory_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rid = get_request_id(request)
    ok_del = await delete_user_memory(db, user_id=user.id, memory_id=memory_id)
    if not ok_del:
        return JSONResponse(status_code=404, content=fail(rid, "NOT_FOUND", "记忆不存在"))
    return JSONResponse(ok(rid, {"deleted": True, "id": memory_id}))
