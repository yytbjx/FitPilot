"""新增模块单测。"""

from __future__ import annotations

from app.eval.agent_eval import run_agent_eval
from app.rag.query_understanding import analyze_query, expand_queries
from app.services.meal_optimizer import optimize_meals
from app.services.progressive_load import apply_progressive_load
from app.services.training_templates import pick_template
from app.services.weekly_adjustment import diagnose_week


def test_pick_template_sessions():
    days = pick_template("muscle_gain", "beginner", 3)
    assert len(days) == 3
    assert "focus" in days[0]


def test_progressive_load_low_completion():
    days = [{"day": 1, "exercises": [{"name": "深蹲", "sets": 4, "reps": 8}]}]
    out = apply_progressive_load(days, {"workout_count": 0}, experience="beginner")
    assert out[0]["exercises"][0]["sets"] <= 4


def test_meal_optimizer():
    foods = [
        {"id": 1, "name": "鸡胸肉", "kcal_per_100g": 165, "protein_g_per_100g": 31},
        {"id": 2, "name": "燕麦", "kcal_per_100g": 389, "protein_g_per_100g": 17},
    ]
    meals = optimize_meals(foods, {"kcal": 2000, "protein_g": 120})
    assert len(meals) == 3


def test_query_understanding_multi():
    info = analyze_query("减脂期间蛋白摄入多少？并且如何安排训练？")
    assert info["use_multi_query"] is True
    assert len(expand_queries("减脂蛋白")) >= 1


def test_weekly_diagnosis():
    diag = diagnose_week(
        {"weekly_sessions": 4, "nutrition_estimate": {"targets": {"kcal": 2000, "protein_g": 120}}},
        {"workout_count": 1, "diet_kcal": 5000, "diet_protein_g": 100},
    )
    assert diag["severity"] in {"medium", "high"}


def test_agent_eval_suite():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    suite = root / "evals" / "agent_routing_cases.json"
    if suite.exists():
        r = run_agent_eval(suite)
        assert r.total >= 10
        assert r.ok, r.summary_text()


def test_plan_diff_changes():
    from app.services.plan_diff import build_plan_diff

    diff = build_plan_diff(
        current_workout={"weekly_sessions": 3, "days": [{"exercises": [1, 2]}]},
        current_diet={"daily_targets": {"kcal": 2000}, "meals": []},
        preview_workout={"weekly_sessions": 4, "days": [{"exercises": [1, 2, 3]}]},
        preview_diet={"daily_targets": {"kcal": 2200}, "meals": []},
    )
    assert diff["has_changes"] is True
    assert any(c["field"] == "workout.weekly_sessions" for c in diff["changes"])
