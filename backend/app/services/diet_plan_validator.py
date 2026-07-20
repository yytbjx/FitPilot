"""膳食计划营养与忌口校验（工程审查 P0）。"""

from __future__ import annotations

from typing import Any


def validate_diet_plan(profile: dict[str, Any], diet: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    targets = diet.get("daily_targets") or {}
    if not targets:
        errors.append("缺少每日营养目标")
    else:
        kcal = float(targets.get("kcal") or targets.get("calories") or 0)
        protein = float(targets.get("protein_g") or 0)
        if kcal < 1200:
            errors.append("每日热量目标低于安全下限(1200 kcal)")
        if kcal > 6000:
            warnings.append("每日热量目标异常偏高，请人工确认")
        if protein < 40:
            warnings.append("蛋白质目标偏低")

    restrictions = (profile.get("restrictions") or "").lower()
    allergies = (profile.get("diet_prefs") or "").lower()
    banned = {x.strip() for x in (restrictions + "," + allergies).split(",") if x.strip()}

    for meal in diet.get("meals") or []:
        idea = str(meal.get("idea") or meal.get("name") or "").lower()
        for b in banned:
            if b and b in idea:
                errors.append(f"餐食可能触犯忌口/过敏：{meal.get('name')}（含 {b}）")

    return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings}
