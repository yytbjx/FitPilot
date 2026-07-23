"""安全 / 边界 / 澄清子图。"""

from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, StateGraph

from app.agents.workflows.safety_workflow import (
    run_boundary_workflow,
    run_clarify_workflow,
    run_safety_workflow,
)
from app.graphs.state import FitnessAgentState

SafetyMode = Literal["safety", "boundary", "clarify"]


def build_safety_subgraph(*, mode: SafetyMode = "safety"):
    """按模式编译单一出口子图，便于独立测试。"""
    handlers = {
        "safety": run_safety_workflow,
        "boundary": run_boundary_workflow,
        "clarify": run_clarify_workflow,
    }
    g = StateGraph(FitnessAgentState)
    g.add_node(mode, handlers[mode])
    g.set_entry_point(mode)
    g.add_edge(mode, END)
    return g.compile()


async def invoke_safety_mode(state: FitnessAgentState, *, mode: SafetyMode) -> dict[str, Any]:
    graph = build_safety_subgraph(mode=mode)
    return await graph.ainvoke(state)
