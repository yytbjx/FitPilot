"""工具调用 Pydantic 契约（工程审查：工具治理）。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    ok: bool
    tool: str
    data: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    message: str | None = None


class RiskCheckInput(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


class RiskCheckOutput(BaseModel):
    risk_level: Literal["low", "high"]
    hits: list[str]
    block_plan_upgrade: bool
    message: str


class PlanPreviewInput(BaseModel):
    user_id: int = Field(gt=0)
    goal_override: str | None = None


class PlanPreviewOutput(BaseModel):
    ok: bool
    preview: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    diff: dict[str, Any] | None = None
    requires_confirmation: bool = False
