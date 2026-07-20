"""训练 / 饮食 / 体测记录 CRUD。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import fail, get_current_user, get_request_id, ok
from app.db.session import get_db
from app.models.body import BodyMetric
from app.models.food import FoodItem
from app.models.logs import DietLog, WorkoutLog
from app.models.user import User
from app.schemas.auth_biz import BodyMetricCreate, DietLogCreate, WorkoutLogCreate
from app.services.nutrition import macros_from_per_100g

router = APIRouter(tags=["logs"])


@router.get("/workouts/logs")
async def list_workout_logs(
    request: Request,
    log_date: date | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rid = get_request_id(request)
    stmt = select(WorkoutLog).where(WorkoutLog.user_id == user.id).order_by(WorkoutLog.log_date.desc())
    if log_date:
        stmt = stmt.where(WorkoutLog.log_date == log_date)
    rows = (await db.scalars(stmt.limit(100))).all()
    return JSONResponse(
        ok(
            rid,
            {
                "items": [
                    {
                        "id": r.id,
                        "user_id": r.user_id,
                        "log_date": r.log_date.isoformat(),
                        "exercise": r.exercise,
                        "exercise_id": r.exercise_id,
                        "sets": r.sets,
                        "reps": r.reps,
                        "weight_kg": r.weight_kg,
                        "duration_min": r.duration_min,
                        "rpe": r.rpe,
                        "notes": r.notes,
                    }
                    for r in rows
                ]
            },
        )
    )


@router.post("/workouts/logs")
async def create_workout_log(
    body: WorkoutLogCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rid = get_request_id(request)
    row = WorkoutLog(user_id=user.id, **body.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return JSONResponse(
        ok(
            rid,
            {
                "id": row.id,
                "user_id": row.user_id,
                "log_date": row.log_date.isoformat(),
                "exercise": row.exercise,
                "exercise_id": row.exercise_id,
                "sets": row.sets,
                "reps": row.reps,
                "weight_kg": row.weight_kg,
                "duration_min": row.duration_min,
                "rpe": row.rpe,
                "notes": row.notes,
            },
        )
    )


@router.delete("/workouts/logs/{log_id}")
async def delete_workout_log(
    log_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rid = get_request_id(request)
    row = await db.scalar(
        select(WorkoutLog).where(WorkoutLog.id == log_id, WorkoutLog.user_id == user.id)
    )
    if not row:
        return JSONResponse(status_code=404, content=fail(rid, "NOT_FOUND", "记录不存在"))
    await db.delete(row)
    await db.commit()
    return JSONResponse(ok(rid, {"deleted": log_id}))


@router.get("/diet/logs")
async def list_diet_logs(
    request: Request,
    log_date: date | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rid = get_request_id(request)
    stmt = select(DietLog).where(DietLog.user_id == user.id).order_by(DietLog.log_date.desc())
    if log_date:
        stmt = stmt.where(DietLog.log_date == log_date)
    rows = (await db.scalars(stmt.limit(100))).all()
    return JSONResponse(
        ok(
            rid,
            {
                "items": [
                    {
                        "id": r.id,
                        "user_id": r.user_id,
                        "log_date": r.log_date.isoformat(),
                        "food_item_id": r.food_item_id,
                        "food_name": r.food_name,
                        "amount_g": r.amount_g,
                        "meal": r.meal,
                        "kcal": r.kcal,
                        "protein_g": r.protein_g,
                        "carb_g": r.carb_g,
                        "fat_g": r.fat_g,
                        "notes": r.notes,
                    }
                    for r in rows
                ]
            },
        )
    )


@router.post("/diet/logs")
async def create_diet_log(
    body: DietLogCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rid = get_request_id(request)
    food: FoodItem | None = None
    food_name = body.food_name
    if body.food_item_id:
        food = await db.scalar(select(FoodItem).where(FoodItem.id == body.food_item_id))
        if food is None:
            return JSONResponse(
                status_code=404, content=fail(rid, "FOOD_NOT_FOUND", "食物不存在")
            )
        food_name = food.name
    if not food_name:
        return JSONResponse(
            status_code=400, content=fail(rid, "FOOD_REQUIRED", "需要 food_item_id 或 food_name")
        )
    if food:
        macros = macros_from_per_100g(
            body.amount_g,
            food.kcal_per_100g,
            food.protein_g_per_100g,
            food.carb_g_per_100g,
            food.fat_g_per_100g,
        )
    else:
        # 无库条目时不允许捏造宏量，仅记重量
        macros = macros_from_per_100g(body.amount_g, 0, 0, 0, 0)

    row = DietLog(
        user_id=user.id,
        log_date=body.log_date,
        food_item_id=body.food_item_id,
        food_name=food_name,
        amount_g=body.amount_g,
        meal=body.meal,
        kcal=macros.kcal,
        protein_g=macros.protein_g,
        carb_g=macros.carb_g,
        fat_g=macros.fat_g,
        notes=body.notes,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return JSONResponse(
        ok(
            rid,
            {
                "id": row.id,
                "user_id": row.user_id,
                "log_date": row.log_date.isoformat(),
                "food_item_id": row.food_item_id,
                "food_name": row.food_name,
                "amount_g": row.amount_g,
                "meal": row.meal,
                "kcal": row.kcal,
                "protein_g": row.protein_g,
                "carb_g": row.carb_g,
                "fat_g": row.fat_g,
                "notes": row.notes,
            },
        )
    )


@router.get("/body-metrics")
async def list_body_metrics(
    request: Request,
    limit: int = Query(default=30, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rid = get_request_id(request)
    rows = (
        await db.scalars(
            select(BodyMetric)
            .where(BodyMetric.user_id == user.id)
            .order_by(BodyMetric.log_date.desc())
            .limit(limit)
        )
    ).all()
    return JSONResponse(
        ok(
            rid,
            {
                "items": [
                    {
                        "id": r.id,
                        "user_id": r.user_id,
                        "log_date": r.log_date.isoformat(),
                        "weight_kg": r.weight_kg,
                        "body_fat_pct": r.body_fat_pct,
                        "waist_cm": r.waist_cm,
                        "notes": r.notes,
                    }
                    for r in rows
                ]
            },
        )
    )


@router.post("/body-metrics")
async def create_body_metric(
    body: BodyMetricCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rid = get_request_id(request)
    row = BodyMetric(user_id=user.id, **body.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return JSONResponse(
        ok(
            rid,
            {
                "id": row.id,
                "user_id": row.user_id,
                "log_date": row.log_date.isoformat(),
                "weight_kg": row.weight_kg,
                "body_fat_pct": row.body_fat_pct,
                "waist_cm": row.waist_cm,
                "notes": row.notes,
            },
        )
    )
