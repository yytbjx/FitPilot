"""FitnessAgentState 定义。"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class FitnessAgentState(TypedDict, total=False):
    user_id: int
    session_id: str
    task_id: str
    trace_id: str
    original_request: str
    intents: list[str]
    entities: dict[str, Any]
    constraints: dict[str, Any]
    user_profile: dict[str, Any]
    current_goal: str
    current_plan_version: int
    workout_summary: dict[str, Any]
    diet_summary: dict[str, Any]
    body_trend: dict[str, Any]
    recovery_status: str
    retrieved_evidence: list[dict[str, Any]]
    tool_results: Annotated[list[dict[str, Any]], operator.add]
    pending_actions: dict[str, Any]
    risk_level: str
    requires_confirmation: bool
    retry_count: int
    final_status: str
    reply: str
    citations: list[dict[str, Any]]
    events: Annotated[list[dict[str, Any]], operator.add]
    approval_decision: dict[str, Any]
    interrupted: bool
    interrupt_payloads: list[dict[str, Any]]
