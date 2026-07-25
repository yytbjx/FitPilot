"""Human-in-the-loop 审批策略与统一审批载荷。

迭代 3：自 agents.runtime.policies 迁入（PEV 声明式框架已移除，
本模块是唯一仍有真实消费方的部分：plan_approval 子图与计划工作流）。
"""

from __future__ import annotations

from typing import Any, Literal

ApprovalAction = Literal[
    "query_knowledge",
    "read_profile",
    "read_logs",
    "compute",
    "preview_plan",
    "commit_plan",
    "rollback_plan",
    "update_preference",
    "batch_write_logs",
    "delete_data",
    "high_risk_advice",
]

# 对照增强方案表 3
REQUIRES_APPROVAL: dict[ApprovalAction, bool] = {
    "query_knowledge": False,
    "read_profile": False,
    "read_logs": False,
    "compute": False,
    "preview_plan": False,
    "commit_plan": True,
    "rollback_plan": True,
    "update_preference": True,
    "batch_write_logs": True,
    "delete_data": True,
    "high_risk_advice": True,  # 实际不执行，转安全提示
}


def requires_approval(action: ApprovalAction) -> bool:
    return bool(REQUIRES_APPROVAL.get(action, True))


def build_approval_payload(
    pending: dict[str, Any],
    *,
    action: ApprovalAction = "commit_plan",
    log_basis: dict[str, Any] | None = None,
    knowledge_citations: list[dict[str, Any]] | None = None,
    risk_notes: list[str] | None = None,
    can_rollback: bool = True,
) -> dict[str, Any]:
    """统一审批展示：操作、Diff、数据依据、知识来源、可否回滚、风险提示。"""
    preview = pending.get("preview") or {}
    return {
        "type": "plan_approval",
        "action": action,
        "requires_approval": requires_approval(action),
        "operation": "将预览中的训练/饮食计划写入正式版本",
        "workout_plan_id": pending.get("workout_plan_id"),
        "plan_id": pending.get("workout_plan_id"),
        "diet_plan_id": pending.get("diet_plan_id"),
        "preview": preview,
        "diff": pending.get("diff"),
        "weekly_reason": pending.get("weekly_reason"),
        "data_basis": {
            "logs": log_basis or {},
            "validation": pending.get("validation"),
        },
        "knowledge_sources": knowledge_citations or [],
        "can_rollback": can_rollback,
        "risk_notes": risk_notes
        or [
            "确认后将生成新的计划版本；可用计划回滚回到上一版本。",
            "若存在伤病史，系统不会自动增强强度。",
        ],
    }
