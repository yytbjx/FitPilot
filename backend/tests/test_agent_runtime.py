"""迭代 3：PEV 简化后的计划工作流 / 路由 / RetrievalPlan 单测。

原 PEV 框架（planner/executor/validator）已移除；本文件改为固定以下语义：
- 复杂调整意图仍走需审批的复杂预览路径；
- 知识问答不进入计划路径；
- 写工具未审批被拒绝（声明表 + 守卫）；
- 预览结果必须产出待确认草稿，否则按 validation_failed 拒绝；
- 校验失败带原因返回，不做假装修复的重试。
"""

import pytest

from app.agents.routing import route_intent
from app.agents.workflows.plan_workflow import build_preview_update
from app.graphs.fitness_graph import classify_intent, is_complex_task
from app.rag.retrieval_plan import build_retrieval_plan
from app.tools.registry import (
    UnapprovedWriteToolError,
    assert_allowed_without_approval,
    assert_write_requires_approval,
    get_tool,
)


def test_complex_adjust_routes_to_approval_path():
    msg = "根据我最近两周的训练记录调整饮食和训练"
    decision = route_intent(msg)
    assert decision.primary_intent == "plan_adjust"
    assert is_complex_task(msg, decision.primary_intent) is True


def test_knowledge_query_not_in_plan_path():
    # 知识问答由主图路由到 RAG 子图，不进入计划预览路径
    assert classify_intent("减脂期蛋白质怎么安排") == "knowledge_query"
    assert is_complex_task("减脂期蛋白质怎么安排", "knowledge_query") is False


def test_write_tool_blocked_without_approval():
    # 写工具未审批被拒绝：声明表 + 调用现场守卫双重固定该不变量
    commit = get_tool("commit_plans")
    assert commit is not None
    assert commit.operation_type == "write"
    assert commit.requires_approval is True
    with pytest.raises(UnapprovedWriteToolError):
        assert_allowed_without_approval("commit_plans")
    # 读/预览工具可安全出现在免审批的预览路径
    assert_allowed_without_approval("get_user_profile_data")
    assert_allowed_without_approval("recent_logs")
    assert_allowed_without_approval("preview_and_stage_plans")
    assert_allowed_without_approval("weekly_adjust_preview")


def test_write_tool_must_keep_approval_gate():
    # 配置漂移守卫：写工具丢失审批门声明时应立即失败
    assert_write_requires_approval("commit_plans")


def test_preview_success_without_pending_is_rejected():
    # 硬校验：预览路径"成功但无待确认草稿"等价于未审批直接写入，必须拒绝
    update = build_preview_update(
        {"ok": True},
        tool="preview_and_stage_plans",
        steps=[{"tool": "preview_and_stage_plans", "result": {}, "status": "ok"}],
    )
    assert update["final_status"] == "validation_failed"
    assert update["pending_actions"] is None
    assert update["requires_confirmation"] is False
    assert "user_profile" not in update


def test_preview_validation_failure_returns_reason():
    # 失败即失败并带原因返回（原 executor 的"自动修复"会跳过失败步骤，已修正）
    update = build_preview_update(
        {"ok": False, "validation": {"errors": ["热量超出目标上限", "存在伤病史时禁止自动增强强度"]}},
        tool="weekly_adjust_preview",
        steps=[{"tool": "weekly_adjust_preview", "result": {}, "status": "error"}],
    )
    assert update["final_status"] == "validation_failed"
    assert "热量超出目标上限" in update["reply"]
    assert "存在伤病史" in update["reply"]
    assert update["pending_actions"] is None


def test_preview_success_builds_approval_event():
    pending = {
        "workout_plan_id": 1,
        "diet_plan_id": 2,
        "preview": {"workout": {"title": "W"}, "diet": {"title": "D"}},
        "validation": {"ok": True},
        "weekly_reason": "完成率偏低",
    }
    update = build_preview_update(
        {"ok": True, "pending": pending, "requires_confirmation": True},
        tool="weekly_adjust_preview",
        steps=[{"tool": "weekly_adjust_preview", "result": {"ok": True}, "status": "ok"}],
        profile={"goal": "fat_loss"},
        logs={"days": 14, "workout_count": 3},
        task_id="t-1",
    )
    assert update["final_status"] == "awaiting_confirmation"
    assert update["requires_confirmation"] is True
    assert update["pending_actions"] == pending
    assert update["user_profile"] == {"goal": "fat_loss"}
    event = update["events"][0]
    assert event["event"] == "approval_required"
    assert event["type"] == "plan_approval"
    assert event["task_id"] == "t-1"
    assert event["weekly_reason"] == "完成率偏低"
    assert event["data_basis"]["logs"]["workout_count"] == 3
    assert "近14天训练3次" in update["reply"]
    assert "完成率偏低" in update["reply"]


def test_retrieval_plan_strategies():
    simple = build_retrieval_plan("什么是蛋白质")
    assert simple.strategy in {"simple_fact", "default", "complex_explain"}
    risky = build_retrieval_plan("胸痛还能训练吗")
    assert risky.strategy == "high_risk"
    assert risky.authority_threshold == 2
    complex_q = build_retrieval_plan("为什么减脂期要同时控制热量并且保证蛋白质摄入")
    assert complex_q.strategy == "complex_explain"
