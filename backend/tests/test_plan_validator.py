"""训练计划硬约束校验单测。"""

from app.services.training_plan_validator import validate_training_plan


def test_training_plan_sessions_match_days():
    profile = {"weekly_sessions": 3, "experience_level": "intermediate"}
    workout = {
        "weekly_sessions": 3,
        "days": [
            {"day": 1, "exercises": [{"name": "深蹲", "sets": 3, "reps": 8, "equipment": "barbell"}]},
            {"day": 2, "exercises": [{"name": "卧推", "sets": 3, "reps": 8, "equipment": "barbell"}]},
            {"day": 3, "exercises": [{"name": "硬拉", "sets": 3, "reps": 6, "equipment": "barbell"}]},
        ],
        "intensity_note": "渐进负荷，注意热身",
    }
    r = validate_training_plan(profile, workout)
    assert r["ok"] is True


def test_training_plan_rejects_too_many_sessions():
    profile = {"weekly_sessions": 2}
    workout = {"weekly_sessions": 5, "days": [{"day": i, "exercises": [{"name": "a", "sets": 3, "reps": 8}]} for i in range(5)]}
    r = validate_training_plan(profile, workout)
    assert r["ok"] is False
