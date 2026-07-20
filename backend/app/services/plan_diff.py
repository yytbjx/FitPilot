"""计划预览与当前生效版本的差异对比。"""

from __future__ import annotations

from typing import Any


def _summarize_workout(plan: dict[str, Any] | None) -> dict[str, Any]:
    if not plan:
        return {"weekly_sessions": 0, "days": 0, "exercise_count": 0}
    days = plan.get("days") or []
    ex_count = sum(len(d.get("exercises") or []) for d in days)
    return {
        "title": plan.get("title"),
        "weekly_sessions": plan.get("weekly_sessions"),
        "days": len(days),
        "exercise_count": ex_count,
    }


def _summarize_diet(plan: dict[str, Any] | None) -> dict[str, Any]:
    if not plan:
        return {"meals": 0, "targets": {}}
    return {
        "title": plan.get("title"),
        "meals": len(plan.get("meals") or []),
        "targets": plan.get("daily_targets") or {},
    }


def build_plan_diff(
    *,
    current_workout: dict[str, Any] | None,
    current_diet: dict[str, Any] | None,
    preview_workout: dict[str, Any],
    preview_diet: dict[str, Any],
) -> dict[str, Any]:
    """生成计划修改前后摘要，供审批页展示。"""
    before_w = _summarize_workout(current_workout)
    after_w = _summarize_workout(preview_workout)
    before_d = _summarize_diet(current_diet)
    after_d = _summarize_diet(preview_diet)

    changes: list[dict[str, Any]] = []
    if before_w.get("weekly_sessions") != after_w.get("weekly_sessions"):
        changes.append(
            {
                "field": "workout.weekly_sessions",
                "before": before_w.get("weekly_sessions"),
                "after": after_w.get("weekly_sessions"),
            }
        )
    if before_w.get("exercise_count") != after_w.get("exercise_count"):
        changes.append(
            {
                "field": "workout.exercise_count",
                "before": before_w.get("exercise_count"),
                "after": after_w.get("exercise_count"),
            }
        )
    if before_d.get("targets") != after_d.get("targets"):
        changes.append(
            {
                "field": "diet.daily_targets",
                "before": before_d.get("targets"),
                "after": after_d.get("targets"),
            }
        )

    return {
        "before": {"workout": before_w, "diet": before_d},
        "after": {"workout": after_w, "diet": after_d},
        "changes": changes,
        "has_changes": bool(changes) or current_workout is None,
    }
