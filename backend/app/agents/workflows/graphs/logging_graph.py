"""打卡引导子图。"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.agents.workflows.personal_workflow import run_logging_workflow
from app.graphs.state import FitnessAgentState


def build_logging_subgraph():
    g = StateGraph(FitnessAgentState)
    g.add_node("logging", run_logging_workflow)
    g.set_entry_point("logging")
    g.add_edge("logging", END)
    return g.compile()
