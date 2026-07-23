"""Result Validator：检查工具步骤与写操作约束。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agents.runtime.planner import ExecutionPlan
from app.agents.runtime.result import AgentStepResult
from app.tools.registry import get_tool


class ValidationReport(BaseModel):
    ok: bool = True
    message: str = ""
    errors: list[str] = Field(default_factory=list)


def validate_plan_execution(
    plan: ExecutionPlan,
    steps: list[AgentStepResult],
    *,
    pending: dict[str, Any] | None = None,
) -> ValidationReport:
    errors: list[str] = []
    by_id = {s.step_id: s for s in steps}

    for step in plan.steps:
        # 委托给知识子图的步骤允许 skipped/delegated
        got = by_id.get(step.step_id)
        if got is None:
            # 可能因修复循环未产出
            continue
        if got.status == "error":
            errors.append(f"{step.tool} 失败：{got.error}")
        for dep in step.depends_on:
            dep_step = by_id.get(dep)
            if dep_step and dep_step.status == "error":
                errors.append(f"{step.step_id} 依赖 {dep} 失败")

    # 禁止未审批写工具出现在成功步骤中
    for s in steps:
        meta = get_tool(s.tool)
        if meta and meta.operation_type == "write" and meta.requires_approval and s.status == "ok":
            errors.append(f"写工具 {s.tool} 不应在未确认阶段直接成功执行")

    if plan.requires_approval and pending is None and not any(
        s.tool in {"preview_and_stage_plans", "weekly_adjust_preview"} for s in steps
    ):
        # 计划类但未产生 preview
        if any(s.tool.startswith("preview") or "plan" in s.tool for s in plan.steps):
            errors.append("需要审批的计划任务未生成 pending preview")

    if errors:
        return ValidationReport(ok=False, message="；".join(errors), errors=errors)
    return ValidationReport(ok=True, message="ok")
