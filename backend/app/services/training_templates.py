"""训练计划模板库（按目标 × 经验 × 周频次）。"""

from __future__ import annotations

from typing import Any

# 模板：focus → body_parts → sets/reps 建议
_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "fat_loss_beginner_3": [
        {"focus": "全身代谢", "body_parts": ["upper legs", "waist", "cardio"], "sets": 3, "reps": 12},
        {"focus": "上肢推拉", "body_parts": ["chest", "back", "upper arms"], "sets": 3, "reps": 12},
        {"focus": "下肢+核心", "body_parts": ["upper legs", "waist"], "sets": 3, "reps": 12},
    ],
    "fat_loss_intermediate_4": [
        {"focus": "下肢力量", "body_parts": ["upper legs", "lower legs"], "sets": 4, "reps": 10},
        {"focus": "推拉复合", "body_parts": ["chest", "back", "shoulders"], "sets": 4, "reps": 10},
        {"focus": "代谢循环", "body_parts": ["waist", "cardio"], "sets": 3, "reps": 15},
        {"focus": "全身巩固", "body_parts": ["upper legs", "back", "waist"], "sets": 3, "reps": 12},
    ],
    "muscle_gain_beginner_3": [
        {"focus": "下肢基础", "body_parts": ["upper legs", "lower legs"], "sets": 3, "reps": 8},
        {"focus": "推类", "body_parts": ["chest", "shoulders", "upper arms"], "sets": 3, "reps": 8},
        {"focus": "拉类", "body_parts": ["back", "upper arms"], "sets": 3, "reps": 8},
    ],
    "muscle_gain_intermediate_4": [
        {"focus": "深蹲日", "body_parts": ["upper legs", "waist"], "sets": 4, "reps": 6},
        {"focus": "卧推日", "body_parts": ["chest", "shoulders", "upper arms"], "sets": 4, "reps": 6},
        {"focus": "硬拉/拉日", "body_parts": ["back", "upper legs"], "sets": 4, "reps": 6},
        {"focus": "辅助+臂肩", "body_parts": ["shoulders", "upper arms", "waist"], "sets": 3, "reps": 10},
    ],
    "maintain_beginner_2": [
        {"focus": "全身维持", "body_parts": ["chest", "back", "upper legs", "waist"], "sets": 3, "reps": 10},
        {"focus": "有氧+核心", "body_parts": ["cardio", "waist"], "sets": 3, "reps": 12},
    ],
    "maintain_intermediate_3": [
        {"focus": "上肢", "body_parts": ["chest", "back", "shoulders"], "sets": 3, "reps": 10},
        {"focus": "下肢", "body_parts": ["upper legs", "lower legs"], "sets": 3, "reps": 10},
        {"focus": "全身", "body_parts": ["waist", "cardio", "upper arms"], "sets": 3, "reps": 12},
    ],
}


def _experience_bucket(level: str | None) -> str:
    lv = (level or "beginner").lower()
    if lv in {"advanced", "expert", "intermediate"}:
        return "intermediate"
    return "beginner"


def pick_template(goal: str | None, experience: str | None, weekly_sessions: int) -> list[dict[str, Any]]:
    """按档案选择模板日结构，不足则循环/截断。"""
    g = goal or "maintain"
    exp = _experience_bucket(experience)
    sessions = max(2, min(int(weekly_sessions or 3), 6))
    key = f"{g}_{exp}_{sessions}"
    if key not in _TEMPLATES:
        # 回退：找同 goal+exp 最接近频次
        candidates = [k for k in _TEMPLATES if k.startswith(f"{g}_{exp}_")]
        if candidates:
            key = sorted(candidates, key=lambda k: abs(int(k.rsplit("_", 1)[-1]) - sessions))[0]
        else:
            key = "maintain_beginner_3"
    days = list(_TEMPLATES[key])
    while len(days) < sessions:
        days.extend(_TEMPLATES[key])
    return days[:sessions]
