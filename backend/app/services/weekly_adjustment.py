"""周联合调整：训练完成率 × 饮食达标 → 诊断与建议变更。"""

from __future__ import annotations

from typing import Any

from app.services.progressive_load import apply_progressive_load


def diagnose_week(profile: dict[str, Any], logs: dict[str, Any]) -> dict[str, Any]:
    """生成周诊断摘要。"""
    sessions = int(profile.get("weekly_sessions") or 3)
    workout_count = int(logs.get("workout_count") or 0)
    completion = workout_count / max(sessions, 1)
    targets = (profile.get("nutrition_estimate") or {}).get("targets") or {}
    target_kcal = float(targets.get("kcal") or 2000) * 7
    target_protein = float(targets.get("protein_g") or 120) * 7
    diet_kcal = float(logs.get("diet_kcal") or 0)
    diet_protein = float(logs.get("diet_protein_g") or 0)

    issues: list[str] = []
    if completion < 0.6:
        issues.append("训练完成率偏低")
    if diet_kcal < target_kcal * 0.75:
        issues.append("饮食热量摄入不足")
    elif diet_kcal > target_kcal * 1.15:
        issues.append("饮食热量超标")
    if diet_protein < target_protein * 0.7:
        issues.append("蛋白质摄入不足")

    return {
        "workout_completion": round(completion, 2),
        "diet_kcal_ratio": round(diet_kcal / max(target_kcal, 1), 2),
        "diet_protein_ratio": round(diet_protein / max(target_protein, 1), 2),
        "issues": issues,
        "severity": "high" if len(issues) >= 2 else ("medium" if issues else "low"),
    }


def build_weekly_adjustment(
    profile: dict[str, Any],
    logs: dict[str, Any],
    workout_preview: dict[str, Any],
    diet_preview: dict[str, Any],
) -> dict[str, Any]:
    """基于诊断调整训练负荷与饮食目标。"""
    diag = diagnose_week(profile, logs)
    changes: dict[str, Any] = {"workout": [], "diet": []}

    days = workout_preview.get("days") or []
    adjusted_days = apply_progressive_load(
        days, logs, experience=profile.get("experience_level")
    )
    if adjusted_days != days:
        changes["workout"].append("根据完成率调整组次/次数")
    workout_preview = {**workout_preview, "days": adjusted_days}

    targets = dict((diet_preview.get("daily_targets") or {}))
    if "饮食热量摄入不足" in diag["issues"]:
        targets["kcal"] = round(float(targets.get("kcal") or 2000) * 1.05)
        changes["diet"].append("热量目标 +5%")
    if "饮食热量超标" in diag["issues"]:
        targets["kcal"] = round(float(targets.get("kcal") or 2000) * 0.95)
        changes["diet"].append("热量目标 -5%")
    if "蛋白质摄入不足" in diag["issues"]:
        targets["protein_g"] = round(float(targets.get("protein_g") or 120) * 1.1)
        changes["diet"].append("蛋白目标 +10%")
    diet_preview = {**diet_preview, "daily_targets": targets}

    reason = "；".join(diag["issues"]) if diag["issues"] else "表现稳定，微调维持"
    return {
        "diagnosis": diag,
        "changes": changes,
        "reason": reason,
        "workout": workout_preview,
        "diet": diet_preview,
    }
