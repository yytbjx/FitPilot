"""渐进负荷规则：基于近期日志微调组次/重量建议。"""

from __future__ import annotations

from typing import Any


def apply_progressive_load(
    workout_days: list[dict[str, Any]],
    logs: dict[str, Any] | None,
    *,
    experience: str | None = None,
) -> list[dict[str, Any]]:
    """根据近 7 天完成率与容量，微调 sets/reps。"""
    logs = logs or {}
    count = int(logs.get("workout_count") or 0)
    sessions_planned = len(workout_days) or 3
    completion = count / max(sessions_planned, 1)
    exp = (experience or "beginner").lower()
    out: list[dict[str, Any]] = []

    for day in workout_days:
        day_copy = dict(day)
        exercises = []
        for ex in day.get("exercises") or []:
            ex_copy = dict(ex)
            sets = int(ex_copy.get("sets") or 3)
            reps = int(ex_copy.get("reps") or 8)
            note_parts: list[str] = []

            if completion >= 0.85 and exp in {"intermediate", "advanced", "expert"}:
                # 完成率高 → 微增容量
                if sets < 5:
                    sets += 1
                    note_parts.append("完成率高，+1 组")
                elif reps < 12:
                    reps += 1
                    note_parts.append("完成率高，+1 次")
            elif completion < 0.5:
                # 完成率低 → 降负荷
                if sets > 2:
                    sets -= 1
                    note_parts.append("完成率偏低，-1 组")
                note_parts.append("优先保证动作质量")

            ex_copy["sets"] = sets
            ex_copy["reps"] = reps
            if note_parts:
                ex_copy["load_note"] = "；".join(note_parts)
            exercises.append(ex_copy)
        day_copy["exercises"] = exercises
        out.append(day_copy)
    return out
