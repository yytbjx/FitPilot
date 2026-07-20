"""意图路由与风险拦截单测。"""

from app.graphs.fitness_graph import classify_intent, is_complex_task
from app.tools.domain import check_risk, validate_constraints


def test_classify_risk():
    assert classify_intent("我胸痛还能继续加训练吗") == "risk_or_medical"


def test_classify_plan_and_knowledge():
    assert classify_intent("帮我生成减脂训练计划") == "plan_create"
    assert classify_intent("减脂期蛋白质怎么安排") == "knowledge_query"


def test_plan_adjust_without_literal_plan_word():
    """调整饮食和训练应识别为 plan_adjust（不必含「计划」二字）。"""
    msg = "根据我最近两周的训练记录调整饮食和训练"
    assert classify_intent(msg) == "plan_adjust"
    assert is_complex_task(msg, "plan_adjust") is True


def test_log_and_boundary_intents():
    assert classify_intent("我练了卧推三组，帮我打卡训练") == "workout_log_write"
    assert classify_intent("我吃了鸡胸肉，帮我记录饮食") == "diet_log_write"
    assert classify_intent("你好呀") == "small_talk"
    assert classify_intent("帮我预测比特币明天涨跌") == "unsupported"


def test_check_risk_blocks():
    r = check_risk("出现晕厥要怎么办")
    assert r["risk_level"] == "high"
    assert r["block_plan_upgrade"] is True


def test_validate_constraints_injury():
    profile = {"injuries": "膝盖不适", "weekly_sessions": 3}
    plan = {"intensity_note": "增强冲击", "weekly_sessions": 3, "meals": []}
    v = validate_constraints(profile, plan)
    assert v["ok"] is False
