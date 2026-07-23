"""知识问答子图（可独立 compile / invoke）。"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from app.agents.workflows.knowledge_workflow import run_knowledge_workflow
from app.graphs.state import FitnessAgentState


def build_knowledge_subgraph():
    g = StateGraph(FitnessAgentState)
    g.add_node("knowledge", run_knowledge_workflow)
    g.set_entry_point("knowledge")
    g.add_edge("knowledge", END)
    return g.compile()


async def run_knowledge_subgraph(state: FitnessAgentState) -> dict[str, Any]:
    """直接调用工作流（主图节点用）；子图编译供单测 / 独立 invoke。"""
    return await run_knowledge_workflow(state)
