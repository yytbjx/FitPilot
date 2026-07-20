"""训练计划硬约束校验（工程审查 P0）。"""

from __future__ import annotations

from typing import Any


def validate_training_plan(profile: dict[str, Any], workout: dict[str, Any]) -> dict[str, Any]:
    """返回 {ok, errors, warnings}；硬约束不满足时 ok=False。"""
    errors: list[str] = []
    warnings: list[str] = []

    sessions_pref = int(profile.get("weekly_sessions") or 3)
    sessions_plan = int(workout.get("weekly_sessions") or sessions_pref)
    if sessions_plan < 1:
        errors.append("每周训练次数至少为 1")
    if sessions_plan > 7:
        errors.append("每周训练次数不能超过 7")
    if sessions_plan > sessions_pref + 1:
        errors.append(f"计划周训练次数({sessions_plan})高于档案设定({sessions_pref})过多")

    days = workout.get("days") or []
    if len(days) != sessions_plan:
        errors.append(f"训练日数量({len(days)})与 weekly_sessions({sessions_plan})不一致")

    experience = (profile.get("experience_level") or "beginner").lower()
    max_exercises_per_day = 8 if experience != "beginner" else 6
    max_sets_per_day = 24 if experience != "beginner" else 18

    injuries = (profile.get("injuries") or "").strip()
    equipment_text = (profile.get("equipment") or "").strip().lower()
    forbidden_equipment: set[str] = set()
    if injuries:
        if any(k in injuries for k in ("腰", "膝", "肩")):
            warnings.append("档案含伤病描述，请人工确认动作选择")
        forbidden_equipment.add("增强")

    muscle_hits: dict[str, int] = {}
    for day in days:
        exercises = day.get("exercises") or []
        if not exercises:
            errors.append(f"第 {day.get('day')} 天未安排任何动作")
        if len(exercises) > max_exercises_per_day:
            errors.append(
                f"第 {day.get('day')} 天动作数({len(exercises)})超过{experience}上限({max_exercises_per_day})"
            )
        day_sets = 0
        for ex in exercises:
            sets = int(ex.get("sets") or 0)
            reps = int(ex.get("reps") or 0)
            day_sets += sets
            if sets < 1 or sets > 8:
                errors.append(f"动作 {ex.get('name')} 组数({sets})不在 1–8 合理范围")
            if reps < 1 or reps > 30:
                errors.append(f"动作 {ex.get('name')} 次数({reps})不在 1–30 合理范围")
            eq = str(ex.get("equipment") or "").lower()
            if equipment_text and eq and eq not in equipment_text and eq not in ("body weight", "bodyweight", "自重"):
                warnings.append(f"动作 {ex.get('name')} 器械({eq})可能不在用户可用器械列表中")
            muscle = str(ex.get("primary_muscle") or ex.get("body_part") or "unknown")
            muscle_hits[muscle] = muscle_hits.get(muscle, 0) + sets
        if day_sets > max_sets_per_day:
            errors.append(f"第 {day.get('day')} 天总组数({day_sets})超过上限({max_sets_per_day})")

    if experience == "beginner" and len(days) > 0:
        total_ex = sum(len(d.get("exercises") or []) for d in days)
        if total_ex > sessions_plan * 5:
            errors.append("新手计划动作总量过高，请降低复杂度")

    warmup_note = str(workout.get("intensity_note") or "")
    if "热身" not in warmup_note and "渐进" not in warmup_note:
        warnings.append("建议在计划中明确热身与渐进负荷说明")

    # 禁止在伤病时自动增强
    if injuries and "增强" in str(workout.get("intensity_note") or ""):
        errors.append("存在伤病史时禁止自动增强训练强度")

    return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings, "muscle_volume": muscle_hits}
