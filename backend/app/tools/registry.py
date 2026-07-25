"""工具声明表（迭代 3 简化版）。

原声明式 Tool Registry 的 handler/input_schema/output_schema/timeout_seconds
等字段从未被任何消费方使用（执行侧是直接函数调用），已删除。仅保留两个
被真实消费的字段：operation_type / requires_approval，用于固定安全不变量：
"写工具必须经人工审批，不能在未审批路径上成功执行"。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

OperationType = Literal["read", "preview", "write"]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    operation_type: OperationType
    requires_approval: bool = False


_TOOLS: dict[str, ToolDefinition] = {
    "check_risk": ToolDefinition("check_risk", "read"),
    "get_user_profile_data": ToolDefinition("get_user_profile_data", "read"),
    "recent_logs": ToolDefinition("recent_logs", "read"),
    "preview_and_stage_plans": ToolDefinition("preview_and_stage_plans", "preview"),
    "weekly_adjust_preview": ToolDefinition("weekly_adjust_preview", "preview"),
    # 唯一的写工具：只能经 plan_approval 子图 interrupt 确认后由 commit 工作流调用
    "commit_plans": ToolDefinition("commit_plans", "write", requires_approval=True),
}


class UnapprovedWriteToolError(PermissionError):
    """写工具在未审批上下文中被调用，或写工具丢失审批门声明。"""


def get_tool(name: str) -> ToolDefinition | None:
    return _TOOLS.get(name)


def list_tools(*, operation_type: OperationType | None = None) -> list[ToolDefinition]:
    items = list(_TOOLS.values())
    if operation_type:
        items = [t for t in items if t.operation_type == operation_type]
    return items


def assert_allowed_without_approval(name: str) -> None:
    """守卫：审批门内的写工具不得出现在免审批执行路径上。

    计划预览路径在调用每个领域函数前显式执行本检查；若未来有人把写工具
    接进预览路径，会在调用现场立即失败，而不是悄悄写入。
    """
    meta = get_tool(name)
    if meta is not None and meta.operation_type == "write" and meta.requires_approval:
        raise UnapprovedWriteToolError(
            f"写工具 {name} 必须经人工审批后才能执行，不能出现在免审批路径"
        )


def assert_write_requires_approval(name: str) -> None:
    """配置漂移守卫：声明为 write 的工具必须带 requires_approval 审批门。"""
    meta = get_tool(name)
    if meta is not None and meta.operation_type == "write" and not meta.requires_approval:
        raise UnapprovedWriteToolError(f"写工具 {name} 缺少 requires_approval 审批门声明")
