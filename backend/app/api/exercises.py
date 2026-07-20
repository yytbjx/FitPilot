"""动作库 API（器械/肌群筛选理念参考 workout.cool）。"""

from __future__ import annotations

import random

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_request_id, ok
from app.db.session import get_db
from app.models.exercise import Exercise
from app.models.user import User

router = APIRouter(prefix="/exercises", tags=["exercises"])


def _out(e: Exercise) -> dict:
    return {
        "id": e.id,
        "external_id": e.external_id,
        "source": e.source,
        "name_en": e.name_en,
        "name_zh": e.name_zh,
        "display_name": e.name_zh or e.name_en,
        "body_part": e.body_part,
        "equipment": e.equipment,
        "primary_muscle": e.primary_muscle,
        "muscle_group": e.muscle_group,
        "secondary_muscles": e.secondary_muscles or [],
        "instructions_zh": e.instructions_zh,
        "steps_zh": e.steps_zh or [],
        "tags": e.tags or [],
        "media_note": e.media_note,
    }


class ShuffleBody(BaseModel):
    """换一组动作（参考 workout.cool /exercises/shuffle）。"""

    body_parts: list[str] = Field(default_factory=list)
    equipments: list[str] = Field(default_factory=list)
    exclude_ids: list[int] = Field(default_factory=list)
    limit: int = Field(default=6, ge=1, le=30)


@router.get("")
async def list_exercises(
    request: Request,
    q: str | None = Query(default=None, description="名称关键词"),
    body_part: str | None = Query(default=None),
    equipment: str | None = Query(default=None),
    muscle: str | None = Query(default=None, description="目标肌群"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rid = get_request_id(request)
    stmt = select(Exercise)
    count_stmt = select(func.count()).select_from(Exercise)
    if q:
        like = f"%{q}%"
        cond = or_(
            Exercise.name_en.ilike(like),
            Exercise.name_zh.ilike(like),
            Exercise.primary_muscle.ilike(like),
            Exercise.equipment.ilike(like),
        )
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if body_part:
        stmt = stmt.where(Exercise.body_part == body_part)
        count_stmt = count_stmt.where(Exercise.body_part == body_part)
    if equipment:
        stmt = stmt.where(Exercise.equipment.ilike(f"%{equipment}%"))
        count_stmt = count_stmt.where(Exercise.equipment.ilike(f"%{equipment}%"))
    if muscle:
        like_m = f"%{muscle}%"
        mcond = or_(
            Exercise.primary_muscle.ilike(like_m),
            Exercise.muscle_group.ilike(like_m),
        )
        stmt = stmt.where(mcond)
        count_stmt = count_stmt.where(mcond)

    total = int(await db.scalar(count_stmt) or 0)
    rows = (
        await db.scalars(stmt.order_by(Exercise.name_en).offset(offset).limit(limit))
    ).all()
    return JSONResponse(
        ok(
            rid,
            {
                "items": [_out(r) for r in rows],
                "count": len(rows),
                "total": total,
                "offset": offset,
                "limit": limit,
            },
        )
    )


@router.get("/facets")
async def exercise_facets(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """返回筛选项（类似 workout.cool 的 equipment/muscles 维度）。"""
    rid = get_request_id(request)

    async def _distinct(col):
        rows = (
            await db.scalars(select(col).where(col.is_not(None)).distinct().order_by(col))
        ).all()
        return [r for r in rows if r]

    return JSONResponse(
        ok(
            rid,
            {
                "body_parts": await _distinct(Exercise.body_part),
                "equipments": await _distinct(Exercise.equipment),
                "muscles": await _distinct(Exercise.primary_muscle),
                "total": int(await db.scalar(select(func.count()).select_from(Exercise)) or 0),
            },
        )
    )


@router.post("/shuffle")
async def shuffle_exercises(
    body: ShuffleBody,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """在器械 ∩ 部位约束下随机抽动作，便于「换一组」体验。"""
    rid = get_request_id(request)
    stmt = select(Exercise)
    if body.body_parts:
        stmt = stmt.where(Exercise.body_part.in_(body.body_parts))
    if body.equipments:
        stmt = stmt.where(or_(*[Exercise.equipment.ilike(f"%{e}%") for e in body.equipments]))
    if body.exclude_ids:
        stmt = stmt.where(Exercise.id.notin_(body.exclude_ids))
    pool = (await db.scalars(stmt.limit(300))).all()
    if not pool:
        return JSONResponse(ok(rid, {"items": [], "count": 0, "message": "NO_EXERCISES_FOUND"}))
    picked = random.sample(pool, k=min(body.limit, len(pool)))
    return JSONResponse(ok(rid, {"items": [_out(r) for r in picked], "count": len(picked)}))


@router.get("/{exercise_id}")
async def get_exercise(
    exercise_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rid = get_request_id(request)
    row = await db.get(Exercise, exercise_id)
    if row is None:
        return JSONResponse(
            status_code=404,
            content={
                "ok": False,
                "error": {"code": "NOT_FOUND", "message": "动作不存在"},
                "request_id": rid,
            },
        )
    return JSONResponse(ok(rid, _out(row)))
