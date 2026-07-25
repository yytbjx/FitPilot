"""计划领域工作流：线性直接函数调用。

迭代 3 重构：移除 Planner—Executor—Validator 声明式框架。原框架中
planner 产出的计划在两个预览入口里被整体改写（形同虚设），executor 的
"自动修复"会跳过失败步骤（重试语义错误），validator 大部分检查随框架
一起失去意义。现在执行链线性可读：

- 简单预览：风险检查 → 读档案 → preview_and_stage_plans → 组状态更新
- 复杂预览：风险检查 → 读档案 → 读近 14 天日志 → weekly_adjust_preview → 组状态更新
- 提交/拒绝：经 plan_approval 子图 interrupt 确认后调用（见 graphs/plan_graph.py）

保留的硬校验（原 validator 中有真实价值的部分，变为显式调用）：
1. 预览路径调用每个领域函数前执行 assert_allowed_without_approval，
   写工具（commit_plans）一旦混入预览路径会立即失败；
2. 预览结果必须携带 pending 草稿（build_preview_update 硬校验），
   "成功但无待确认草稿"等价于未审批直接写入，按 validation_failed 拒绝；
3. commit 入口执行 assert_write_requires_approval，防止审批门声明被改坏。

失败语义：预览校验失败即失败，带校验原因返回，不做假装修复的重试。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.workflows.approval import build_approval_payload
from app.core.progress import emit_progress
from app.graphs.state import FitnessAgentState
from app.tools.domain import (
    check_risk,
    get_user_profile_data,
    preview_and_stage_plans,
    recent_logs,
    weekly_adjust_preview,
)
from app.tools.registry import assert_allowed_without_approval, assert_write_requires_approval

_PREVIEW_TOOLS = {"preview_and_stage_plans", "weekly_adjust_preview"}


def _summarize(out: Any) -> dict[str, Any]:
    if not isinstance(out, dict):
        return {"value": str(out)[:200]}
    keys = ("ok", "workout_count", "diet_kcal", "pending", "validation", "goal", "weight_kg")
    return {k: out[k] for k in keys if k in out}


def build_preview_update(
    out: dict[str, Any],
    *,
    tool: str,
    steps: list[dict[str, Any]],
    profile: dict[str, Any] | None = None,
    logs: dict[str, Any] | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """把预览工具结果组装成图状态更新（纯函数，便于单测）。

    失败（校验不过或无 pending 草稿）→ validation_failed，带原因返回。
    成功 → awaiting_confirmation + approval_required 审批事件。
    """
    if not out.get("ok"):
        errors = list((out.get("validation") or {}).get("errors") or [])
        reply = "计划未通过约束校验：" + ("；".join(errors) if errors else "未知校验错误")
        return {
            "reply": reply,
            "citations": [],
            "final_status": "validation_failed",
            "pending_actions": None,
            "requires_confirmation": False,
            "events": [{"event": "completed", "status": "validation_failed"}],
            "tool_results": steps,
        }

    pending = out.get("pending")
    if not isinstance(pending, dict) or not pending or out.get("requires_confirmation") is not True:
        # 硬校验：预览路径绝不允许"成功但无待确认草稿"——那等价于未审批直接写入
        return {
            "reply": f"{tool} 未生成待确认的计划草稿，已阻止直接写入正式版本。",
            "citations": [],
            "final_status": "validation_failed",
            "pending_actions": None,
            "requires_confirmation": False,
            "events": [{"event": "completed", "status": "validation_failed"}],
            "tool_results": steps,
        }

    diag: list[str] = []
    if isinstance(logs, dict) and "workout_count" in logs:
        diag.append(f"近{logs.get('days', 7)}天训练{logs.get('workout_count')}次")
    if pending.get("weekly_reason"):
        diag.append(str(pending["weekly_reason"]))
    reply = "已生成训练+饮食计划预览，请确认后再写入正式版本。"
    if diag:
        reply += f"（{'；'.join(diag)}）"

    approval = build_approval_payload(
        pending,
        log_basis=_summarize(logs) if isinstance(logs, dict) else None,
    )
    event = {"event": "approval_required", **approval, "task_id": task_id}
    update: dict[str, Any] = {
        "reply": reply,
        "citations": [],
        "final_status": "awaiting_confirmation",
        "pending_actions": pending,
        "requires_confirmation": True,
        "events": [event],
        "tool_results": steps,
    }
    if profile:
        update["user_profile"] = profile
    return update


async def run_plan_preview_workflow(state: FitnessAgentState, *, db: AsyncSession) -> dict[str, Any]:
    """简单计划预览：读档案 → 生成训练+饮食预览并暂存草稿。"""
    if state.get("risk_level") == "high" or check_risk(state.get("original_request", ""))["risk_level"] == "high":
        from app.agents.workflows.safety_workflow import run_safety_workflow

        return await run_safety_workflow(state)

    user_id = state["user_id"]
    request_id = state.get("trace_id")

    assert_allowed_without_approval("get_user_profile_data")
    profile = await get_user_profile_data(db, user_id)
    emit_progress(
        stage="tool_executor",
        title="工具完成：get_user_profile_data",
        detail="plan_preview",
        tool="get_user_profile_data",
        status="done",
    )

    assert_allowed_without_approval("preview_and_stage_plans")
    out = await preview_and_stage_plans(db, user_id, profile, request_id=request_id)
    emit_progress(
        stage="tool_executor",
        title="工具完成：preview_and_stage_plans",
        detail="plan_preview",
        tool="preview_and_stage_plans",
        status="done",
    )

    steps = [
        {"tool": "get_user_profile_data", "result": _summarize(profile), "status": "ok"},
        {
            "tool": "preview_and_stage_plans",
            "result": _summarize(out),
            "status": "ok" if out.get("ok") else "error",
        },
    ]
    return build_preview_update(
        out,
        tool="preview_and_stage_plans",
        steps=steps,
        profile=profile if out.get("ok") else None,
        task_id=state.get("task_id"),
    )


async def run_complex_plan_workflow(state: FitnessAgentState, *, db: AsyncSession) -> dict[str, Any]:
    """复杂计划预览：档案 → 近 14 天日志 → 周联合调整预览。"""
    if state.get("risk_level") == "high":
        from app.agents.workflows.safety_workflow import run_safety_workflow

        return await run_safety_workflow(state)

    user_id = state["user_id"]
    request_id = state.get("trace_id")

    assert_allowed_without_approval("get_user_profile_data")
    profile = await get_user_profile_data(db, user_id)

    assert_allowed_without_approval("recent_logs")
    logs = await recent_logs(db, user_id, days=14)

    assert_allowed_without_approval("weekly_adjust_preview")
    out = await weekly_adjust_preview(db, user_id, profile, request_id=request_id)
    emit_progress(
        stage="tool_executor",
        title="工具完成：weekly_adjust_preview",
        detail="complex_preview",
        tool="weekly_adjust_preview",
        status="done",
    )

    steps = [
        {"tool": "get_user_profile_data", "result": _summarize(profile), "status": "ok"},
        {"tool": "recent_logs", "result": _summarize(logs), "status": "ok"},
        {
            "tool": "weekly_adjust_preview",
            "result": _summarize(out),
            "status": "ok" if out.get("ok") else "error",
        },
    ]
    return build_preview_update(
        out,
        tool="weekly_adjust_preview",
        steps=steps,
        profile=profile if out.get("ok") else None,
        logs=logs,
        task_id=state.get("task_id"),
    )


async def run_plan_commit_workflow(state: FitnessAgentState, *, db: AsyncSession) -> dict[str, Any]:
    from app.application.plans import commit_plan_use_case

    # 审批门配置漂移守卫：commit 是唯一的写工具，必须始终保持 requires_approval
    assert_write_requires_approval("commit_plans")

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
