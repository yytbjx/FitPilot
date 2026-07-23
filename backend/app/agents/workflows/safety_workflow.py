"""安全 / 边界 / 澄清工作流。"""

from __future__ import annotations

from typing import Any

from app.agents.routing import route_intent
from app.core.progress import emit_progress
from app.graphs.state import FitnessAgentState


async def run_safety_workflow(state: FitnessAgentState) -> dict[str, Any]:
    emit_progress(stage="safety", title="安全节点", detail="阻断自动增强训练", tool="check_risk", status="done")
    msg = (
        "检测到可能与伤病/医疗相关的高风险表述。"
        "FitPilot 不能提供诊断或治疗建议，也不会自动增强训练计划。请尽快咨询医生。"
    )
    return {
        "reply": msg,
        "final_status": "blocked_safety",
        "requires_confirmation": False,
        "events": [{"event": "completed", "status": "blocked_safety"}],
    }


async def run_boundary_workflow(state: FitnessAgentState) -> dict[str, Any]:
    emit_progress(stage="boundary", title="边界说明", status="done")
    return {
        "reply": "我是 FitPilot 健身与膳食助手。可以问营养/训练知识，或让我生成计划预览。",
        "final_status": "completed",
        "events": [{"event": "completed", "status": "small_talk"}],
    }


async def run_clarify_workflow(state: FitnessAgentState) -> dict[str, Any]:
    decision = route_intent(state.get("original_request", ""))
    q = decision.clarify_question or "请更具体地说明你想做什么（知识问答 / 个人数据 / 生成或调整计划）。"
    emit_progress(stage="clarify", title="意图澄清", detail=q, status="done")
    return {
        "reply": q,
        "final_status": "completed",
        "events": [{"event": "completed", "status": "clarify", "routing": decision.model_dump()}],
        "tool_results": [{"tool": "route_intent", "result": decision.model_dump()}],
    }
