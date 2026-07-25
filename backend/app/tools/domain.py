"""领域工具：白名单 + 确定性计算。"""

from __future__ import annotations

import random
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.audit import AuditLog
from app.models.exercise import Exercise
from app.models.food import FoodItem
from app.models.plan_adjustment import PlanAdjustment
from app.models.plans import DietPlan, WorkoutPlan
from app.services.diet_plan_validator import validate_diet_plan
from app.services.meal_optimizer import optimize_meals
from app.services.plan_diff import build_plan_diff
from app.services.progressive_load import apply_progressive_load
from app.services.training_plan_validator import validate_training_plan
from app.services.training_templates import pick_template
from app.services.weekly_adjustment import build_weekly_adjustment

RISK_KEYWORDS = [
    "胸痛",
    "晕厥",
    "呼吸困难",
    "急性损伤",
    "心脏病",
    "吃药",
    "处方",
    "诊断",
    "骨折",
]


def check_risk(text: str) -> dict[str, Any]:
    hits = [k for k in RISK_KEYWORDS if k in (text or "")]
    level = "high" if hits else "low"
    return {
        "risk_level": level,
        "hits": hits,
        "block_plan_upgrade": level == "high",
        "message": "检测到高风险医疗相关表述，已停止自动增强训练计划，请及时就医。"
        if hits
        else "风险检查通过",
    }


async def get_user_profile_data(db: AsyncSession, user_id: int) -> dict[str, Any]:
    from app.infrastructure.persistence.user_repository import SqlUserRepository

    return await SqlUserRepository(db).get_profile_dict(user_id)


async def query_foods(db: AsyncSession, q: str | None = None, limit: int = 10) -> list[dict]:
    stmt = select(FoodItem).order_by(FoodItem.name).limit(limit)
    if q:
        stmt = stmt.where(FoodItem.name.ilike(f"%{q}%"))
    rows = (await db.scalars(stmt)).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "kcal_per_100g": r.kcal_per_100g,
            "protein_g_per_100g": r.protein_g_per_100g,
        }
        for r in rows
    ]


# 档案里常见的中文器械 → exercises-dataset equipment 值
_EQUIPMENT_ALIASES: dict[str, list[str]] = {
    "哑铃": ["dumbbell"],
    "杠铃": ["barbell"],
    "器械": ["cable", "leverage machine", "smith machine"],
    "拉力器": ["cable"],
    "龙门架": ["cable"],
    "徒手": ["body weight"],
    "自重": ["body weight"],
    "自身体重": ["body weight"],
    "弹力带": ["band", "resistance band"],
    "壶铃": ["kettlebell"],
    "固定器械": ["leverage machine", "smith machine"],
}

_FOCUS_BODY_PARTS: list[tuple[str, list[str]]] = [
    ("全身力量", ["chest", "back", "upper legs", "waist"]),
    ("上肢", ["chest", "upper arms", "shoulders", "back"]),
    ("下肢", ["upper legs", "lower legs", "waist"]),
    ("核心耐力", ["waist", "cardio"]),
]


def _equipment_filters(profile_equipment: str | None) -> list[str]:
    raw = (profile_equipment or "").strip()
    if not raw:
        return ["body weight", "dumbbell", "barbell", "cable"]
    hit: list[str] = []
    for cn, ens in _EQUIPMENT_ALIASES.items():
        if cn in raw:
            hit.extend(ens)
    # 也允许直接写英文
    lowered = raw.lower()
    for token in ["dumbbell", "barbell", "cable", "body weight", "kettlebell", "band"]:
        if token in lowered:
            hit.append(token)
    return list(dict.fromkeys(hit)) or ["body weight"]


async def query_exercises(
    db: AsyncSession,
    *,
    q: str | None = None,
    body_part: str | None = None,
    equipment: str | None = None,
    muscle: str | None = None,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """按 workout.cool 理念做多维筛选，供 Agent/计划生成使用。"""
    from sqlalchemy import or_

    stmt = select(Exercise)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Exercise.name_en.ilike(like),
                Exercise.name_zh.ilike(like),
                Exercise.primary_muscle.ilike(like),
            )
        )
    if body_part:
        stmt = stmt.where(Exercise.body_part == body_part)
    if equipment:
        stmt = stmt.where(Exercise.equipment.ilike(f"%{equipment}%"))
    if muscle:
        like_m = f"%{muscle}%"
        stmt = stmt.where(
            or_(
                Exercise.primary_muscle.ilike(like_m),
                Exercise.muscle_group.ilike(like_m),
            )
        )
    rows = (await db.scalars(stmt.order_by(Exercise.name_en).limit(limit))).all()
    return [
        {
            "id": r.id,
            "external_id": r.external_id,
            "name": r.name_zh or r.name_en,
            "name_en": r.name_en,
            "name_zh": r.name_zh,
            "body_part": r.body_part,
            "equipment": r.equipment,
            "primary_muscle": r.primary_muscle,
            "secondary_muscles": r.secondary_muscles or [],
        }
        for r in rows
    ]


async def _pick_day_exercises(
    db: AsyncSession,
    *,
    body_parts: list[str],
    equipments: list[str],
    per_day: int = 3,
) -> list[dict[str, Any]]:
    from sqlalchemy import or_

    picked: list[dict[str, Any]] = []
    seen: set[int] = set()
    for bp in body_parts:
        if len(picked) >= per_day:
            break
        conds = [Exercise.body_part == bp]
        if equipments:
            conds.append(or_(*[Exercise.equipment.ilike(f"%{e}%") for e in equipments]))
        rows = (
            await db.scalars(
                select(Exercise).where(*conds).order_by(Exercise.id).limit(8)
            )
        ).all()
        for r in rows:
            if r.id in seen:
                continue
            seen.add(r.id)
            picked.append(
                {
                    "exercise_id": r.id,
                    "external_id": r.external_id,
                    "name": r.name_zh or r.name_en,
                    "name_en": r.name_en,
                    "body_part": r.body_part,
                    "equipment": r.equipment,
                    "primary_muscle": r.primary_muscle,
                    "sets": 3,
                    "reps": 8 if bp != "cardio" else 12,
                }
            )
            if len(picked) >= per_day:
                break
    # 库为空时回退硬编码，保证计划仍可生成
    if not picked:
        return [
            {"name": "深蹲", "sets": 3, "reps": 8},
            {"name": "俯卧撑", "sets": 3, "reps": 10},
            {"name": "平板支撑", "sets": 3, "reps": 30},
        ]
    # 打乱顺序，贴近 workout.cool 的 shuffle 体验
    random.shuffle(picked)
    return picked


async def build_plan_preview(
    db: AsyncSession, profile: dict[str, Any], *, logs: dict[str, Any] | None = None
) -> dict[str, Any]:
    goal = profile.get("goal") or "maintain"
    sessions = int(profile.get("weekly_sessions") or 3)
    targets = (profile.get("nutrition_estimate") or {}).get("targets") or {}
    equipments = _equipment_filters(profile.get("equipment"))
    template_days = pick_template(goal, profile.get("experience_level"), sessions)

    days = []
    for i, tpl in enumerate(template_days):
        exercises = await _pick_day_exercises(
            db,
            body_parts=tpl["body_parts"],
            equipments=equipments,
            per_day=3,
        )
        for ex in exercises:
            ex.setdefault("sets", tpl.get("sets", 3))
            ex.setdefault("reps", tpl.get("reps", 8))
        days.append({"day": i + 1, "focus": tpl["focus"], "exercises": exercises})

    if logs:
        days = apply_progressive_load(days, logs, experience=profile.get("experience_level"))

    workout = {
        "title": f"{goal} 训练计划",
        "weekly_sessions": sessions,
        "equipment_filter": equipments,
        "days": days,
        "template_key": f"{goal}_{profile.get('experience_level') or 'beginner'}_{sessions}",
        "intensity_note": "基于模板库 + 渐进负荷规则；以可控强度渐进，不以疼痛换进度",
        "design_note": "训练模板库 → 器械筛选 → 渐进负荷微调",
    }

    foods = await query_foods(db, limit=30)
    from app.core.config import get_settings

    meals = optimize_meals(
        foods,
        targets,
        profile=profile,
        use_ortools=get_settings().meal_use_ortools,
    )
    diet = {
        "title": f"{goal} 饮食目标",
        "daily_targets": targets,
        "meals": meals,
        "notes": "宏量由确定性计算给出，食谱经 OR-Tools 约束优化（失败则贪心）从食物库选取",
    }
    return {"workout": workout, "diet": diet, "goal": goal}


async def recent_logs(db: AsyncSession, user_id: int, days: int = 7) -> dict[str, Any]:
    from app.infrastructure.persistence.user_repository import SqlUserRepository

    return await SqlUserRepository(db).recent_logs(user_id, days=days)


def validate_constraints(profile: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """合并训练硬约束 + 膳食校验 + 旧版规则。"""
    workout = plan if "days" in plan else plan.get("workout") or {}
    diet = plan.get("diet") or {"meals": plan.get("meals"), "daily_targets": plan.get("daily_targets")}
    w_val = validate_training_plan(profile, workout)
    d_val = validate_diet_plan(profile, diet)
    errors = list(w_val.get("errors") or []) + list(d_val.get("errors") or [])
    warnings = list(w_val.get("warnings") or []) + list(d_val.get("warnings") or [])
    injuries = (profile.get("injuries") or "").strip()
    if injuries and "增强" in str(workout.get("intensity_note") or ""):
        errors.append("存在伤病史时禁止自动增强强度")
    return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings}


async def _stage_plan_preview(
    db: AsyncSession,
    user_id: int,
    profile: dict[str, Any],
    preview: dict[str, Any],
    *,
    request_id: str | None = None,
    audit_message: str = "生成计划预览，等待确认",
    extra_pending: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validation = validate_constraints(
        profile, {"workout": preview["workout"], "diet": preview["diet"], "meals": preview["diet"]["meals"]}
    )
    if not validation["ok"]:
        return {"ok": False, "validation": validation, "preview": preview}

    w_plan = await db.scalar(
        select(WorkoutPlan)
        .where(WorkoutPlan.user_id == user_id, WorkoutPlan.status.in_(["active", "draft"]))
        .order_by(WorkoutPlan.id.desc())
        .options(selectinload(WorkoutPlan.versions))
    )
    if w_plan is None:
        w_plan = WorkoutPlan(user_id=user_id, title=preview["workout"]["title"], status="draft", current_version=0)
        db.add(w_plan)
        await db.flush()

    d_plan = await db.scalar(
        select(DietPlan)
        .where(DietPlan.user_id == user_id, DietPlan.status.in_(["active", "draft"]))
        .order_by(DietPlan.id.desc())
        .options(selectinload(DietPlan.versions))
    )
    if d_plan is None:
        d_plan = DietPlan(user_id=user_id, title=preview["diet"]["title"], status="draft", current_version=0)
        db.add(d_plan)
        await db.flush()

    current_w = None
    current_d = None
    if w_plan and w_plan.versions:
        cv = next((v for v in w_plan.versions if v.version == w_plan.current_version), None)
        current_w = cv.content if cv else None
    if d_plan and d_plan.versions:
        cv = next((v for v in d_plan.versions if v.version == d_plan.current_version), None)
        current_d = cv.content if cv else None

    diff = build_plan_diff(
        current_workout=current_w,
        current_diet=current_d,
        preview_workout=preview["workout"],
        preview_diet=preview["diet"],
    )

    pending = {
        "workout_plan_id": w_plan.id,
        "diet_plan_id": d_plan.id,
        "preview": preview,
        "validation": validation,
        "diff": diff,
        "next_workout_version": (w_plan.current_version or 0) + 1,
        "next_diet_version": (d_plan.current_version or 0) + 1,
    }
    if extra_pending:
        pending.update(extra_pending)
    # 幂等暂存：同一请求（任务重试共享同一 request_id/trace_id）只保留最新草稿，
    # 先作废旧草稿再插入，保证 worker 重试不产生多份 staged 草稿
    if request_id:
        await db.execute(
            delete(AuditLog).where(
                AuditLog.user_id == user_id,
                AuditLog.action == "plan_preview",
                AuditLog.request_id == request_id,
            )
        )
    db.add(
        AuditLog(
            user_id=user_id,
            action="plan_preview",
            resource_type="workout_plan",
            resource_id=str(w_plan.id),
            detail=pending,
            request_id=request_id,
            message=audit_message,
        )
    )
    await db.commit()
    return {"ok": True, "pending": pending, "requires_confirmation": True}


async def preview_and_stage_plans(
    db: AsyncSession, user_id: int, profile: dict[str, Any], request_id: str | None = None
) -> dict[str, Any]:
    logs = await recent_logs(db, user_id)
    preview = await build_plan_preview(db, profile, logs=logs)
    return await _stage_plan_preview(db, user_id, profile, preview, request_id=request_id)


async def commit_plans(db: AsyncSession, user_id: int, pending: dict[str, Any]) -> dict[str, Any]:
    """兼容入口：委托 Application + UnitOfWork。"""
    from app.application.plans import commit_plan_use_case

    return await commit_plan_use_case(db, user_id=user_id, pending=pending)


async def rollback_plan(db: AsyncSession, user_id: int, workout_plan_id: int) -> dict[str, Any]:
    from app.application.plans import rollback_workout_plan_use_case

    return await rollback_workout_plan_use_case(db, user_id=user_id, workout_plan_id=workout_plan_id)


async def weekly_adjust_preview(
    db: AsyncSession, user_id: int, profile: dict[str, Any], request_id: str | None = None
) -> dict[str, Any]:
    """周联合调整：诊断 → 训练/饮食联动修改 → 预览。"""
    logs = await recent_logs(db, user_id)
    base = await build_plan_preview(db, profile, logs=logs)
    adjusted = build_weekly_adjustment(profile, logs, base["workout"], base["diet"])
    preview = {"workout": adjusted["workout"], "diet": adjusted["diet"], "goal": base["goal"]}
    validation = validate_constraints(
        profile, {"workout": preview["workout"], "diet": preview["diet"], "meals": preview["diet"]["meals"]}
    )
    if not validation["ok"]:
        return {"ok": False, "validation": validation, "preview": preview, "diagnosis": adjusted["diagnosis"]}

    # 幂等暂存：worker 重试前先把该用户未确认的旧的周调整草稿作废
    await db.execute(
        update(PlanAdjustment)
        .where(PlanAdjustment.user_id == user_id, PlanAdjustment.status == "pending")
        .values(status="superseded")
    )
    db.add(
        PlanAdjustment(
            user_id=user_id,
            diagnosis=adjusted["diagnosis"],
            changes=adjusted["changes"],
            reason=adjusted["reason"],
            status="pending",
        )
    )
    await db.flush()
    return await _stage_plan_preview(
        db,
        user_id,
        profile,
        preview,
        request_id=request_id,
        audit_message="周联合调整预览，等待确认",
        extra_pending={
            "weekly_diagnosis": adjusted["diagnosis"],
            "weekly_changes": adjusted["changes"],
            "weekly_reason": adjusted["reason"],
        },
    )
