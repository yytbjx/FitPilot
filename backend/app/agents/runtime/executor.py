"""Tool Executor：按 ExecutionPlan 逐步调用白名单工具（最多自动修复一次）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runtime.exceptions import ToolExecutionError, ValidationFailed
from app.agents.runtime.planner import ExecutionPlan, PlanStep
from app.agents.runtime.policies import MAX_AUTO_REPAIR
from app.agents.runtime.result import AgentRunResult, AgentStepResult
from app.agents.runtime.validator import validate_plan_execution
from app.core.progress import emit_progress
from app.tools.domain import (
    get_user_profile_data,
    preview_and_stage_plans,
    recent_logs,
    weekly_adjust_preview,
)
from app.tools.registry import get_tool


async def execute_plan(
    plan: ExecutionPlan,
    *,
    db: AsyncSession,
    user_id: int,
    message: str,
    request_id: str | None = None,
) -> AgentRunResult:
    """执行结构化计划；写操作仅到 preview，commit 仍走 interrupt 确认。"""
    emit_progress(
        stage="planner",
        title="结构化执行计划",
        detail=f"goal={plan.goal} steps={len(plan.steps)}",
        tool="build_execution_plan",
        status="done",
        extra=plan.model_dump(),
    )
    results: dict[str, Any] = {}
    steps_out: list[AgentStepResult] = []
    profile: dict[str, Any] = {}
    pending: dict[str, Any] | None = None
    repairs = 0

    for step in plan.steps:
        try:
            out = await _run_step(
                step,
                db=db,
                user_id=user_id,
                message=message,
                request_id=request_id,
                ctx=results,
            )
            results[step.step_id] = out
            if step.tool == "get_user_profile_data":
                profile = out if isinstance(out, dict) else {}
            if step.tool in {"preview_and_stage_plans", "weekly_adjust_preview"}:
                if not out.get("ok"):
                    raise ValidationFailed(
                        "计划校验失败",
                        errors=list((out.get("validation") or {}).get("errors") or []),
                    )
                pending = out.get("pending")
            steps_out.append(
                AgentStepResult(
                    step_id=step.step_id,
                    tool=step.tool,
                    status="ok",
                    input_summary=step.arguments,
                    output_summary=_summarize(out),
                )
            )
            emit_progress(
                stage="tool_executor",
                title=f"工具完成：{step.tool}",
                detail=step.step_id,
                tool=step.tool,
                status="done",
            )
        except ValidationFailed as exc:
            steps_out.append(
                AgentStepResult(
                    step_id=step.step_id,
                    tool=step.tool,
                    status="error",
                    error=str(exc),
                    retry_count=repairs,
                )
            )
            if repairs < MAX_AUTO_REPAIR and step.tool in {
                "preview_and_stage_plans",
                "weekly_adjust_preview",
            }:
                repairs += 1
                emit_progress(
                    stage="validator_repair",
                    title="自动修复重试",
                    detail=f"第 {repairs} 次：放宽后重试预览",
                    tool=step.tool,
                )
                # 简单修复：再读一次档案后重试
                profile = await get_user_profile_data(db, user_id)
                results["c1"] = profile
                continue
            return AgentRunResult(
                ok=False,
                status="validation_failed",
                reply="计划未通过约束校验：" + "；".join(exc.errors or [str(exc)]),
                steps=steps_out,
            )
        except Exception as exc:  # noqa: BLE001
            steps_out.append(
                AgentStepResult(
                    step_id=step.step_id,
                    tool=step.tool,
                    status="error",
                    error=str(exc),
                )
            )
            raise ToolExecutionError(step.tool, str(exc)) from exc

    validation = validate_plan_execution(plan, steps_out, pending=pending)
    if not validation.ok:
        return AgentRunResult(
            ok=False,
            status="validation_failed",
            reply=validation.message,
            steps=steps_out,
        )

    if pending:
        diag = []
        logs = results.get("c2") or results.get("p2")
        if isinstance(logs, dict) and "workout_count" in logs:
            diag.append(f"近{logs.get('days', 7)}天训练{logs.get('workout_count')}次")
        if pending.get("weekly_reason"):
            diag.append(str(pending["weekly_reason"]))
        reply = "已生成训练+饮食计划预览，请确认后再写入正式版本。"
        if diag:
            reply += f"（{'；'.join(diag)}）"
        return AgentRunResult(
            ok=True,
            status="awaiting_confirmation",
            reply=reply,
            pending_actions=pending,
            requires_approval=True,
            steps=steps_out,
            metadata={"profile": profile},
        )

    # 知识 / 个人数据路径由专用 workflow 处理；此处仅计划 PEV
    return AgentRunResult(
        ok=True,
        status="completed",
        reply="执行计划已完成。",
        steps=steps_out,
        metadata={"profile": profile},
    )


async def _run_step(
    step: PlanStep,
    *,
    db: AsyncSession,
    user_id: int,
    message: str,
    request_id: str | None,
    ctx: dict[str, Any],
) -> Any:
    meta = get_tool(step.tool)
    if meta and meta.operation_type == "write" and meta.requires_approval:
        raise ToolExecutionError(step.tool, "写操作必须经人工确认，不能在 Executor 中直接执行")

    if step.tool == "get_user_profile_data":
        return await get_user_profile_data(db, user_id)
    if step.tool == "recent_logs":
        days = int(step.arguments.get("days") or 7)
        return await recent_logs(db, user_id, days=days)
    if step.tool == "preview_and_stage_plans":
        profile = ctx.get("c1") or await get_user_profile_data(db, user_id)
        return await preview_and_stage_plans(db, user_id, profile, request_id=request_id)
    if step.tool == "weekly_adjust_preview":
        profile = ctx.get("c1") or await get_user_profile_data(db, user_id)
        return await weekly_adjust_preview(db, user_id, profile, request_id=request_id)
    if step.tool == "log_hint":
        return {"hint": "请在记录页打卡"}
    if step.tool in {"hybrid_retrieve", "assess_evidence", "generate_answer"}:
        return {"delegated": True, "tool": step.tool}
    raise ToolExecutionError(step.tool, "未注册或未实现的执行器")


def _summarize(out: Any) -> dict[str, Any]:
    if not isinstance(out, dict):
        return {"value": str(out)[:200]}
    keys = ("ok", "workout_count", "diet_kcal", "pending", "validation", "goal", "weight_kg")
    return {k: out[k] for k in keys if k in out}
