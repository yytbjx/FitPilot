"""结构化 Task Planner（输出步骤清单，非自然语言思维链）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agents.routing import RoutingDecision, route_intent


class PlanStep(BaseModel):
    step_id: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)


class ExecutionPlan(BaseModel):
    goal: str
    steps: list[PlanStep] = Field(default_factory=list)
    requires_approval: bool = False
    routing: dict[str, Any] = Field(default_factory=dict)


def build_execution_plan(message: str, *, routing: RoutingDecision | None = None) -> ExecutionPlan:
    decision = routing or route_intent(message)
    intent = decision.primary_intent
    steps: list[PlanStep] = []
    requires_approval = decision.requires_approval

    if intent == "risk_or_medical":
        return ExecutionPlan(goal="安全拦截", steps=[], routing=decision.model_dump())

    if intent == "clarify":
        return ExecutionPlan(goal="澄清意图", steps=[], routing=decision.model_dump())

    # 知识问答不在 Planner-Executor 中展开：由 knowledge_workflow（RAG 子图）专用处理，
    # 因此 knowledge_query 意图下 steps 保持为空（此前 s1/s2/s3 在 Executor 中仅返回
    # {"delegated": True}，属无效步骤，已移除）。

    if intent == "personal_data_query" or decision.requires_personal_data:
        steps.append(PlanStep(step_id="p1", tool="get_user_profile_data", arguments={}))
        steps.append(PlanStep(step_id="p2", tool="recent_logs", arguments={"days": 7}, depends_on=["p1"]))

    if intent in {"plan_create", "plan_adjust"}:
        if decision.requires_personal_data or "最近" in message or "两周" in message:
            steps.append(PlanStep(step_id="c1", tool="get_user_profile_data", arguments={}))
            steps.append(
                PlanStep(step_id="c2", tool="recent_logs", arguments={"days": 14}, depends_on=["c1"])
            )
            steps.append(
                PlanStep(
                    step_id="c3",
                    tool="weekly_adjust_preview",
                    arguments={},
                    depends_on=["c2"],
                )
            )
        else:
            steps.append(PlanStep(step_id="c1", tool="get_user_profile_data", arguments={}))
            steps.append(
                PlanStep(step_id="c2", tool="preview_and_stage_plans", arguments={}, depends_on=["c1"])
            )
        requires_approval = True

    if intent in {"workout_log_write", "diet_log_write"}:
        steps.append(PlanStep(step_id="l1", tool="log_hint", arguments={}))

    goal_map = {
        "knowledge_query": "知识问答",
        "personal_data_query": "个人数据汇总",
        "plan_create": "生成训练/饮食计划预览",
        "plan_adjust": "根据近期数据调整计划",
        "workout_log_write": "引导训练打卡",
        "diet_log_write": "引导饮食打卡",
        "small_talk": "边界说明",
        "unsupported": "边界说明",
    }
    return ExecutionPlan(
        goal=goal_map.get(intent, intent),
        steps=steps,
        requires_approval=requires_approval,
        routing=decision.model_dump(),
    )
