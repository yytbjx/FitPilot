"""结构化意图路由（增强方案 4.2）。"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from app.tools.domain import check_risk

Intent = Literal[
    "knowledge_query",
    "personal_data_query",
    "plan_create",
    "plan_adjust",
    "workout_log_write",
    "diet_log_write",
    "risk_or_medical",
    "small_talk",
    "unsupported",
    "clarify",
]


class RoutingDecision(BaseModel):
    primary_intent: Intent
    secondary_intents: list[Intent] = Field(default_factory=list)
    confidence: float = 0.0
    requires_personal_data: bool = False
    requires_knowledge: bool = False
    requires_write: bool = False
    requires_approval: bool = False
    missing_fields: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"] = "low"
    clarify_question: str | None = None


_CONFIDENCE_GATE = 0.55


def route_intent(text: str) -> RoutingDecision:
    """三级路由的前两级：高风险/边界规则 + 高置信规则；低置信进入 clarify。"""
    t = text or ""
    risk = check_risk(t)
    if risk["risk_level"] == "high":
        return RoutingDecision(
            primary_intent="risk_or_medical",
            confidence=0.99,
            risk_level="high",
            requires_write=False,
        )

    if re.search(r"(写代码|写.*代码|股票|炒股|比特币|加密货币|算命|占卜)", t):
        return RoutingDecision(primary_intent="unsupported", confidence=0.95, risk_level="low")

    secondary: list[Intent] = []
    primary: Intent | None = None
    confidence = 0.0
    missing: list[str] = []

    # 多意图：分析 + 调整
    has_analyze = bool(re.search(r"(分析|看看|最近|情况|趋势|完成率)", t))
    has_adjust = bool(re.search(r"(调整|改一下|优化).*(计划|训练|饮食)|(计划|训练|饮食).*(调整|改)", t))
    has_plan = bool(re.search(r"(计划|安排训练|生成计划|换个饮食|调整饮食|调整训练)", t))
    has_knowledge = bool(re.search(r"(蛋白|减脂|增肌|热量|深蹲|硬拉|食谱|怎么|如何|什么|知识|原则)", t))
    has_personal = bool(re.search(r"(我的档案|我的体重|我的记录|本周训练|营养目标|最近训练)", t))
    has_workout_log = bool(re.search(r"(我练了|打卡训练|记录训练)", t))
    has_diet_log = bool(re.search(r"(我吃了|记录饮食|打卡饮食)", t))
    has_small = bool(re.search(r"(你好|您好|谢谢|哈哈)", t))

    if has_plan and "调整" in t:
        primary = "plan_adjust"
        confidence = 0.88
    elif has_plan:
        primary = "plan_create"
        confidence = 0.86
    elif has_workout_log:
        primary = "workout_log_write"
        confidence = 0.9
    elif has_diet_log:
        primary = "diet_log_write"
        confidence = 0.9
    elif has_personal:
        primary = "personal_data_query"
        confidence = 0.85
    elif has_knowledge:
        primary = "knowledge_query"
        confidence = 0.8
    elif has_small:
        primary = "small_talk"
        confidence = 0.92

    if has_analyze and primary in {"plan_adjust", "plan_create", None}:
        secondary.append("personal_data_query")
        if primary is None:
            primary = "plan_adjust" if has_adjust else "personal_data_query"
            confidence = 0.7
    if has_knowledge and primary in {"plan_create", "plan_adjust"}:
        secondary.append("knowledge_query")
    if has_analyze and primary == "knowledge_query":
        secondary.append("personal_data_query")

    if primary is None:
        # 不再默认无脑进入 RAG：低置信澄清
        return RoutingDecision(
            primary_intent="clarify",
            confidence=0.35,
            missing_fields=["intent"],
            clarify_question="请补充你的目标：是知识问答、查看个人数据，还是生成/调整训练饮食计划？",
            risk_level="low",
        )

    if confidence < _CONFIDENCE_GATE:
        return RoutingDecision(
            primary_intent="clarify",
            secondary_intents=[primary, *secondary],
            confidence=confidence,
            missing_fields=["intent_clarity"],
            clarify_question="我不太确定你的意图，请用更明确的一句话描述你想做的事。",
            risk_level="low",
        )

    requires_write = primary in {"plan_create", "plan_adjust", "workout_log_write", "diet_log_write"}
    requires_approval = primary in {"plan_create", "plan_adjust"}
    requires_personal = primary in {
        "personal_data_query",
        "plan_create",
        "plan_adjust",
    } or "personal_data_query" in secondary
    requires_knowledge = primary == "knowledge_query" or "knowledge_query" in secondary

    if primary in {"plan_create", "plan_adjust"} and not re.search(r"(天|周|器械|目标|减脂|增肌)", t):
        missing.append("goal_or_schedule")

    return RoutingDecision(
        primary_intent=primary,
        secondary_intents=list(dict.fromkeys(secondary)),
        confidence=confidence,
        requires_personal_data=requires_personal,
        requires_knowledge=requires_knowledge,
        requires_write=requires_write,
        requires_approval=requires_approval,
        missing_fields=missing,
        risk_level="low",
        clarify_question=("请补充训练天数、目标或可用器械，以便生成更合适的计划。" if missing else None),
    )
