"""个人数据查询子图。"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.workflows.personal_workflow import run_personal_workflow
from app.graphs.state import FitnessAgentState


def build_personal_subgraph(db: AsyncSession):
    async def _node(state: FitnessAgentState) -> dict[str, Any]:
        return await run_personal_workflow(state, db=db)

    g = StateGraph(FitnessAgentState)
    g.add_node("personal", _node)
    g.set_entry_point("personal")
    g.add_edge("personal", END)
    return g.compile()
