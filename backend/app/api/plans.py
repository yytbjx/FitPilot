"""计划读写：当前计划、预览、批准、回滚。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import fail, get_current_user, get_request_id, ok
from app.db.session import get_db
from app.models.plans import DietPlan, WorkoutPlan
from app.models.user import User
from app.schemas.auth_biz import MealSwapRequest, PlanApproveRequest, PlanPreviewRequest
from app.services.meal_optimizer import meal_macro_totals, swap_meal_item
from app.tools.domain import (
    commit_plans,
    get_user_profile_data,
    preview_and_stage_plans,
    rollback_plan,
    weekly_adjust_preview,
)

router = APIRouter(prefix="/plans", tags=["plans"])


@router.get("/current")
async def current_plans(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rid = get_request_id(request)
    w_plan = await db.scalar(
        select(WorkoutPlan)
        .where(WorkoutPlan.user_id == user.id, WorkoutPlan.status == "active")
        .options(selectinload(WorkoutPlan.versions))
        .order_by(WorkoutPlan.id.desc())
    )
    d_plan = await db.scalar(
        select(DietPlan)
        .where(DietPlan.user_id == user.id, DietPlan.status == "active")
        .options(selectinload(DietPlan.versions))
        .order_by(DietPlan.id.desc())
    )

    def pack(p, kind: str):
        if not p:
            return None
        versions = sorted(p.versions, key=lambda v: v.version, reverse=True)
        latest = versions[0] if versions else None
        current = next((v for v in versions if v.version == p.current_version), latest)
        return {
            "id": p.id,
            "kind": kind,
            "title": p.title,
            "status": p.status,
            "current_version": p.current_version,
            "latest": None
            if not current
            else {
                "version": current.version,
                "content": current.content,
                "change_summary": current.change_summary,
            },
        }

    return JSONResponse(ok(rid, {"workout": pack(w_plan, "workout"), "diet": pack(d_plan, "diet")}))


@router.post("/preview")
async def preview_plans(
    body: PlanPreviewRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rid = get_request_id(request)
    profile = await get_user_profile_data(db, user.id)
    if body.goal_override:
        profile["goal"] = body.goal_override
    staged = await preview_and_stage_plans(db, user.id, profile, request_id=rid)
    if not staged.get("ok"):
        return JSONResponse(
            status_code=400,
            content=fail(rid, "VALIDATION_FAILED", "计划未通过校验", details=staged),
        )
    pending = staged["pending"]
    return JSONResponse(
        ok(
            rid,
            {
                "workout_plan_id": pending["workout_plan_id"],
                "diet_plan_id": pending["diet_plan_id"],
                "preview": pending["preview"],
                "diff": pending.get("diff"),
                "requires_confirmation": True,
            },
        )
    )


@router.post("/{plan_id}/approve")
async def approve_plan(
    plan_id: int,
    body: PlanApproveRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rid = get_request_id(request)
    w_plan = await db.scalar(
        select(WorkoutPlan).where(WorkoutPlan.id == plan_id, WorkoutPlan.user_id == user.id)
    )
    if not w_plan:
        return JSONResponse(status_code=404, content=fail(rid, "NOT_FOUND", "计划不存在"))
    if not body.approve:
        w_plan.status = "draft"
        await db.commit()
        return JSONResponse(ok(rid, {"approved": False, "plan_id": plan_id}))

    if body.pending:
        result = await commit_plans(db, user.id, body.pending)
        return JSONResponse(ok(rid, {"approved": True, **result}))

    # 回退：重新生成预览（兼容旧客户端）
    profile = await get_user_profile_data(db, user.id)
    staged = await preview_and_stage_plans(db, user.id, profile, request_id=rid)
    if not staged.get("ok"):
        return JSONResponse(
            status_code=400,
            content=fail(rid, "VALIDATION_FAILED", "无法提交", details=staged),
        )
    result = await commit_plans(db, user.id, staged["pending"])
    return JSONResponse(ok(rid, {"approved": True, **result}))


@router.post("/{plan_id}/rollback")
async def rollback(
    plan_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rid = get_request_id(request)
    result = await rollback_plan(db, user.id, plan_id)
    if not result.get("ok"):
        return JSONResponse(
            status_code=400, content=fail(rid, result.get("error", "ROLLBACK_FAILED"), "回滚失败")
        )
    return JSONResponse(ok(rid, result))


@router.post("/weekly-adjust")
async def weekly_adjust(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """周联合调整：基于近期日志诊断并生成预览。"""
    rid = get_request_id(request)
    profile = await get_user_profile_data(db, user.id)
    staged = await weekly_adjust_preview(db, user.id, profile, request_id=rid)
    if not staged.get("ok"):
        return JSONResponse(
            status_code=400,
            content=fail(rid, "VALIDATION_FAILED", "周调整未通过校验", details=staged),
        )
    pending = staged["pending"]
    return JSONResponse(
        ok(
            rid,
            {
                "workout_plan_id": pending["workout_plan_id"],
                "diet_plan_id": pending["diet_plan_id"],
                "preview": pending["preview"],
                "diff": pending.get("diff"),
                "weekly_diagnosis": pending.get("weekly_diagnosis"),
                "weekly_changes": pending.get("weekly_changes"),
                "weekly_reason": pending.get("weekly_reason"),
                "requires_confirmation": True,
            },
        )
    )


@router.post("/meals/swap")
async def swap_meal(
    body: MealSwapRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """单餐换菜并重优化（锁定其余餐次）。"""
    from app.core.config import get_settings
    from app.tools.domain import query_foods

    rid = get_request_id(request)
    profile = await get_user_profile_data(db, user.id)
    foods = await query_foods(db, limit=50)
    result = swap_meal_item(
        body.meals,
        meal_index=body.meal_index,
        foods=foods,
        daily_targets=body.daily_targets,
        profile=profile,
        swap_food_id=body.swap_food_id,
        use_ortools=get_settings().meal_use_ortools,
    )
    if not result.get("ok"):
        return JSONResponse(
            status_code=400,
            content=fail(rid, result.get("error", "SWAP_FAILED"), "换菜失败"),
        )
    return JSONResponse(ok(rid, result))
