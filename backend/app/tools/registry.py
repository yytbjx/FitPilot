"""Tool Registry：声明式工具契约（增强方案 4.4）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field


class EmptyInput(BaseModel):
    pass


class TextInput(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)


class DaysInput(BaseModel):
    days: int = Field(default=7, ge=1, le=90)


@dataclass
class ToolDefinition:
    name: str
    description: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel] | None
    permission: str
    operation_type: Literal["read", "preview", "write"]
    timeout_seconds: int = 30
    idempotent: bool = True
    requires_approval: bool = False
    handler: Callable[..., Any] | None = None
    tags: list[str] = field(default_factory=list)


_REGISTRY: dict[str, ToolDefinition] = {}


def register_tool(defn: ToolDefinition) -> ToolDefinition:
    _REGISTRY[defn.name] = defn
    return defn


def get_tool(name: str) -> ToolDefinition | None:
    return _REGISTRY.get(name)


def list_tools(*, operation_type: str | None = None) -> list[ToolDefinition]:
    items = list(_REGISTRY.values())
    if operation_type:
        items = [t for t in items if t.operation_type == operation_type]
    return items


def ensure_default_tools() -> None:
    """注册内置领域工具元数据（handler 仍走 domain 模块）。"""
    if _REGISTRY:
        return
    from app.tools import domain

    register_tool(
        ToolDefinition(
            name="check_risk",
            description="高风险医疗表述检测",
            input_schema=TextInput,
            output_schema=None,
            permission="agent",
            operation_type="read",
            idempotent=True,
            requires_approval=False,
            handler=domain.check_risk,
            tags=["safety"],
        )
    )
    register_tool(
        ToolDefinition(
            name="get_user_profile_data",
            description="读取用户档案与营养目标",
            input_schema=EmptyInput,
            output_schema=None,
            permission="user",
            operation_type="read",
            handler=domain.get_user_profile_data,
            tags=["profile"],
        )
    )
    register_tool(
        ToolDefinition(
            name="recent_logs",
            description="读取近期训练/饮食日志摘要",
            input_schema=DaysInput,
            output_schema=None,
            permission="user",
            operation_type="read",
            handler=domain.recent_logs,
            tags=["log"],
        )
    )
    register_tool(
        ToolDefinition(
            name="preview_and_stage_plans",
            description="生成训练+饮食计划预览（不写生效版本）",
            input_schema=EmptyInput,
            output_schema=None,
            permission="user",
            operation_type="preview",
            requires_approval=False,
            idempotent=False,
            handler=domain.preview_and_stage_plans,
            tags=["plan"],
        )
    )
    register_tool(
        ToolDefinition(
            name="commit_plans",
            description="确认写入计划版本",
            input_schema=EmptyInput,
            output_schema=None,
            permission="user",
            operation_type="write",
            requires_approval=True,
            idempotent=True,
            handler=domain.commit_plans,
            tags=["plan", "write"],
        )
    )
    register_tool(
        ToolDefinition(
            name="weekly_adjust_preview",
            description="周联合调整诊断与预览",
            input_schema=EmptyInput,
            output_schema=None,
            permission="user",
            operation_type="preview",
            handler=domain.weekly_adjust_preview,
            tags=["plan"],
        )
    )


# 模块导入时注册
ensure_default_tools()
