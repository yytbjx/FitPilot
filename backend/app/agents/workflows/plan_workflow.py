"""计划领域工作流（含 Planner—Executor—Validator）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runtime.executor import execute_plan
from app.agents.runtime.planner import build_execution_plan
from app.agents.routing import route_intent
from app.graphs.state import FitnessAgentState
from app.tools.domain import check_risk


async def run_plan_preview_workflow(state: FitnessAgentState, *, db: AsyncSession) -> dict[str, Any]:
    if state.get("risk_level") == "high" or check_risk(state.get("original_request", ""))["risk_level"] == "high":
        from app.agents.workflows.safety_workflow import run_safety_workflow

        return await run_safety_workflow(state)

    message = state.get("original_request", "")
    routing = route_intent(message)
    plan = build_execution_plan(message, routing=routing)
    # 简单计划：去掉复杂周调整步骤
    plan.steps = [s for s in plan.steps if s.tool != "weekly_adjust_preview"]
    if not any(s.tool == "preview_and_stage_plans" for s in plan.steps):
        from app.agents.runtime.planner import PlanStep

        plan.steps.append(
            PlanStep(step_id="c2", tool="preview_and_stage_plans", arguments={}, depends_on=["c1"])
        )

    result = await execute_plan(
        plan,
        db=db,
        user_id=state["user_id"],
        message=message,
        request_id=state.get("trace_id"),
    )
    update = result.to_state_update()
    if result.metadata.get("profile"):
        update["user_profile"] = result.metadata["profile"]
    if result.requires_approval and result.pending_actions:
        # 附加 task_id，便于前端 approve
        events = update.get("events") or []
        if events:
            events[0]["task_id"] = state.get("task_id")
            update["events"] = events
    return update


async def run_complex_plan_workflow(state: FitnessAgentState, *, db: AsyncSession) -> dict[str, Any]:
    """复杂计划：完整 PEV（档案→日志→周调整预览）。"""
    if state.get("risk_level") == "high":
        from app.agents.workflows.safety_workflow import run_safety_workflow

        return await run_safety_workflow(state)

    message = state.get("original_request", "")
    routing = route_intent(message)
    plan = build_execution_plan(message, routing=routing)
    # 强制走周调整路径
    from app.agents.runtime.planner import PlanStep

    plan.steps = [
        PlanStep(step_id="c1", tool="get_user_profile_data", arguments={}),
        PlanStep(step_id="c2", tool="recent_logs", arguments={"days": 14}, depends_on=["c1"]),
        PlanStep(step_id="c3", tool="weekly_adjust_preview", arguments={}, depends_on=["c2"]),
    ]
    plan.requires_approval = True
    plan.goal = "根据近期数据调整下周训练/饮食计划"

    result = await execute_plan(
        plan,
        db=db,
        user_id=state["user_id"],
        message=message,
        request_id=state.get("trace_id"),
    )
    # 把日志依据塞进 metadata，供审批载荷展示
    log_basis = None
    for s in result.steps:
        if s.tool == "recent_logs" and s.output_summary:
            log_basis = s.output_summary
    if log_basis:
        result.metadata["log_basis"] = log_basis
    update = result.to_state_update()
    if result.metadata.get("profile"):
        update["user_profile"] = result.metadata["profile"]
    if result.requires_approval and result.pending_actions:
        events = update.get("events") or []
        if events:
            events[0]["task_id"] = state.get("task_id")
            events[0]["weekly_reason"] = (result.pending_actions or {}).get("weekly_reason")
            update["events"] = events
    return update


async def run_plan_commit_workflow(state: FitnessAgentState, *, db: AsyncSession) -> dict[str, Any]:
    from app.application.plans import commit_plan_use_case

    pending = state.get("pending_actions") or {}
    result = await commit_plan_use_case(
        db,
        user_id=state["user_id"],
        pending=pending,
        task_id=state.get("task_id"),
    )
    comment = (state.get("approval_decision") or {}).get("comment")
    if not result.get("ok"):
        return {
            "reply": f"计划提交失败：{result.get('error') or 'unknown'}",
            "final_status": "failed",
            "pending_actions": None,
            "events": [{"event": "failed", "status": "plan_commit_failed", **result}],
            "tool_results": [{"tool": "commit_plans", "result": result}],
        }
    msg = "计划已批准并写入正式版本。"
    if comment:
        msg += f"（备注：{comment}）"
    return {
        "reply": msg,
        "final_status": "completed",
        "pending_actions": None,
        "events": [{"event": "completed", "status": "plan_committed", **result}],
        "tool_results": [{"tool": "commit_plans", "result": result}],
    }


async def run_plan_reject_workflow(state: FitnessAgentState) -> dict[str, Any]:
    comment = (state.get("approval_decision") or {}).get("comment")
    msg = "已取消计划写入，预览保持草稿状态。"
    if comment:
        msg += f"（备注：{comment}）"
    return {
        "reply": msg,
        "final_status": "rejected",
        "pending_actions": None,
        "events": [{"event": "completed", "status": "plan_rejected"}],
    }
