"""计划预览 / 审批子图。"""

from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, StateGraph
from langgraph.types import interrupt
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.workflows.plan_workflow import (
    run_complex_plan_workflow,
    run_plan_commit_workflow,
    run_plan_preview_workflow,
    run_plan_reject_workflow,
)
from app.core.progress import emit_progress
from app.graphs.state import FitnessAgentState

PlanPreviewMode = Literal["simple", "complex"]


def build_plan_preview_subgraph(db: AsyncSession, *, mode: PlanPreviewMode = "simple"):
    async def _node(state: FitnessAgentState) -> dict[str, Any]:
        if mode == "complex":
            return await run_complex_plan_workflow(state, db=db)
        return await run_plan_preview_workflow(state, db=db)

    g = StateGraph(FitnessAgentState)
    g.add_node("plan_preview", _node)
    g.set_entry_point("plan_preview")
    g.add_edge("plan_preview", END)
    return g.compile()


def build_plan_approval_subgraph(db: AsyncSession):
    """confirm → commit | reject（含 interrupt）。"""

    async def confirm(state: FitnessAgentState) -> dict[str, Any]:
        from app.agents.workflows.approval import build_approval_payload

        pending = state.get("pending_actions") or {}
        emit_progress(
            stage="plan_confirm",
            title="等待用户确认",
            detail="plan approval subgraph interrupt",
            tool="interrupt",
            status="done",
        )
        raw = interrupt(build_approval_payload(pending))
        decision = raw if isinstance(raw, dict) else {"approve": bool(raw)}
        return {
            "approval_decision": decision,
            "requires_confirmation": False,
            "events": [{"event": "approval_decision", "decision": decision}],
        }

    async def commit(state: FitnessAgentState) -> dict[str, Any]:
        return await run_plan_commit_workflow(state, db=db)

    async def reject(state: FitnessAgentState) -> dict[str, Any]:
        return await run_plan_reject_workflow(state)

    def route(state: FitnessAgentState) -> str:
        decision = state.get("approval_decision") or {}
        return "commit" if decision.get("approve") else "reject"

    g = StateGraph(FitnessAgentState)
    g.add_node("confirm", confirm)
    g.add_node("commit", commit)
    g.add_node("reject", reject)
    g.set_entry_point("confirm")
    g.add_conditional_edges("confirm", route, {"commit": "commit", "reject": "reject"})
    g.add_edge("commit", END)
    g.add_edge("reject", END)
    return g.compile()
