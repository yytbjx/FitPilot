"""食物库 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import fail, get_current_user, get_request_id, ok
from app.db.session import get_db
from app.models.food import FoodItem
from app.models.user import User
from app.schemas.auth_biz import FoodCreate

router = APIRouter(prefix="/foods", tags=["foods"])


def _food_out(f: FoodItem) -> dict:
    return {
        "id": f.id,
        "source": getattr(f, "source", None) or "manual",
        "external_id": getattr(f, "external_id", None),
        "name": f.name,
        "name_en": getattr(f, "name_en", None),
        "brand": f.brand,
        "category": f.category,
        "serving_g": f.serving_g,
        "kcal_per_100g": f.kcal_per_100g,
        "protein_g_per_100g": f.protein_g_per_100g,
        "carb_g_per_100g": f.carb_g_per_100g,
        "fat_g_per_100g": f.fat_g_per_100g,
    }


@router.get("")
async def list_foods(
    request: Request,
    q: str | None = Query(default=None),
    source: str | None = Query(default=None, description="manual | usda-foundation"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rid = get_request_id(request)
    stmt = select(FoodItem)
    count_stmt = select(func.count()).select_from(FoodItem)
    if q:
        like = f"%{q}%"
        cond = or_(
            FoodItem.name.ilike(like),
            FoodItem.name_en.ilike(like),
            FoodItem.category.ilike(like),
        )
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if source:
        stmt = stmt.where(FoodItem.source == source)
        count_stmt = count_stmt.where(FoodItem.source == source)
    total = int(await db.scalar(count_stmt) or 0)
    rows = (await db.scalars(stmt.order_by(FoodItem.name).offset(offset).limit(limit))).all()
    return JSONResponse(
        ok(
            rid,
            {
                "items": [_food_out(r) for r in rows],
                "count": len(rows),
                "total": total,
                "offset": offset,
                "limit": limit,
            },
        )
    )


@router.post("")
async def create_food(
    body: FoodCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rid = get_request_id(request)
    exists = await db.scalar(select(FoodItem).where(FoodItem.name == body.name))
    if exists:
        return JSONResponse(status_code=409, content=fail(rid, "FOOD_EXISTS", "食物已存在"))
    item = FoodItem(**body.model_dump(), source="manual", external_id=None)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return JSONResponse(ok(rid, _food_out(item)))
