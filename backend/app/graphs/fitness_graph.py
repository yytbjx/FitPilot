"""LangGraph 健身 Agent 主图（实时进度推送 + 协作式取消）。"""

from __future__ import annotations

import re
from typing import Any, Literal

from langgraph.graph import END, StateGraph
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.progress import emit_progress
from app.db.session import get_engine
from app.graphs.checkpointer import PostgresCheckpointSaver, load_latest_checkpoint_state
from app.graphs.runner_utils import normalize_graph_result
from app.graphs.state import FitnessAgentState
from app.services.agent_cancellation import AgentTaskCancelledError, CancelCheckerFn
from app.services.ollama_client import get_ollama_client
from app.tools.domain import check_risk

Intent = Literal[
    "knowledge_query",
    "personal_data_query",
    "plan_create",
    "plan_adjust",
    "workout_log_write",
    "diet_log_write",
    "risk_or_medical",
    "small_talk",
    "unsupported",
    "clarify",
]

INTENT_LABELS = {
    "knowledge_query": "知识问答（RAG）",
    "personal_data_query": "个人数据查询",
    "plan_create": "生成训练/饮食计划",
    "plan_adjust": "调整计划",
    "workout_log_write": "训练打卡引导",
    "diet_log_write": "饮食打卡引导",
    "risk_or_medical": "高风险安全拦截",
    "small_talk": "闲聊/边界说明",
    "unsupported": "未支持意图",
    "clarify": "意图澄清",
}


def classify_intent(text: str) -> Intent:
    """结构化路由（规则级）；未知意图进入 clarify，不再默认 RAG。"""
    from app.agents.routing import route_intent

    return route_intent(text).primary_intent


def _intent_confident(text: str) -> bool:
    from app.agents.routing import route_intent

    decision = route_intent(text)
    return decision.primary_intent != "clarify" and decision.confidence >= 0.55


async def classify_intent_async(text: str) -> Intent:
    """规则优先；可选 0.5B 辅助分类（仅不确定时调用，省显存）。"""
    intent = classify_intent(text)
    settings = get_settings()
    if not settings.ollama_use_llm_classify or _intent_confident(text):
        return intent
    labels = ", ".join(INTENT_LABELS.keys())
    prompt = (
        f"从下列意图中选一个最匹配的英文标签，只输出标签本身：\n{labels}\n\n"
        f"用户说：{text}"
    )
    try:
        resp = await get_ollama_client().chat(
            [
                {"role": "system", "content": "你是意图分类器，只输出一个意图标签。"},
                {"role": "user", "content": prompt},
            ],
            role="classify",
            options={"num_predict": 16, "temperature": 0.0},
        )
        raw = ((resp.get("message") or {}).get("content") or "").strip().lower()
        for key in INTENT_LABELS:
            if key in raw or key.replace("_", " ") in raw:
                return key  # type: ignore[return-value]
    except Exception:  # noqa: BLE001
        pass
    return intent


async def node_classify(state: FitnessAgentState) -> dict[str, Any]:
    settings = get_settings()
    emit_progress(
        stage="classify",
        title="意图分类与风险检查",
        detail=(
            "工具：check_risk + 规则路由"
            + (" + 小模型辅助" if settings.ollama_use_llm_classify else "")
        ),
        tool="check_risk",
    )
    intent = await classify_intent_async(state.get("original_request", ""))
    risk = check_risk(state.get("original_request", ""))
    emit_progress(
        stage="classify",
        title="路由完成",
        detail=f"意图={INTENT_LABELS.get(intent, intent)}；风险={risk['risk_level']}",
        tool="check_risk",
        status="done",
        extra={"intent": intent, "risk": risk},
    )
    return {
        "intents": [intent],
        "risk_level": risk["risk_level"],
        "events": [
            {
                "event": "node_started",
                "node": "classify",
                "intent": intent,
                "intent_label": INTENT_LABELS.get(intent, intent),
            }
        ],
        "tool_results": [{"tool": "check_risk", "result": risk}],
    }


# 节点实现已迁入 agents/workflows/graphs/* 编译子图；主图仅组装路由。


def is_complex_task(text: str, intent: Intent) -> bool:
    """复杂任务：需多步读取个人数据再联合调整计划。"""
    if intent not in {"plan_create", "plan_adjust"}:
        return False
    return bool(
        re.search(
            r"(最近|两周|一周|体重|记录|联合|根据|调整|完成率|趋势|表现)",
            text or "",
        )
    )


def route_after_plan_preview(state: FitnessAgentState) -> str:
    if state.get("final_status") in {"validation_failed", "blocked_safety", "no_answer"}:
        return "end"
    return "approval"


def route_after_classify(state: FitnessAgentState) -> str:
    intent = (state.get("intents") or ["unsupported"])[0]
    if intent == "risk_or_medical":
        return "safety"
    if intent == "clarify":
        return "clarify"
    if is_complex_task(state.get("original_request", ""), intent):
        return "complex_preview"
    if intent in {"plan_create", "plan_adjust"}:
        return "plan_preview"
    if intent == "personal_data_query":
        return "personal"
    if intent in {"workout_log_write", "diet_log_write"}:
        return "log_hint"
    if intent in {"small_talk", "unsupported"}:
        return "boundary"
    return "rag"


def build_fitness_graph(
    db: AsyncSession,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
):
    from app.agents.workflows.graphs import (
        build_knowledge_subgraph,
        build_logging_subgraph,
        build_personal_subgraph,
        build_plan_approval_subgraph,
        build_plan_preview_subgraph,
        build_safety_subgraph,
    )

    if session_factory is None:
        session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)

    g = StateGraph(FitnessAgentState)
    g.add_node("classify", node_classify)
    g.add_node("safety", build_safety_subgraph(mode="safety"))
    g.add_node("boundary", build_safety_subgraph(mode="boundary"))
    g.add_node("clarify", build_safety_subgraph(mode="clarify"))
    g.add_node("rag", build_knowledge_subgraph())
    g.add_node("personal", build_personal_subgraph(db))
    g.add_node("plan_preview", build_plan_preview_subgraph(db, mode="simple"))
    g.add_node("complex_preview", build_plan_preview_subgraph(db, mode="complex"))
    g.add_node("plan_approval", build_plan_approval_subgraph(db))
    g.add_node("log_hint", build_logging_subgraph())
    g.set_entry_point("classify")
    g.add_conditional_edges(
        "classify",
        route_after_classify,
        {
            "safety": "safety",
            "boundary": "boundary",
            "clarify": "clarify",
            "rag": "rag",
            "personal": "personal",
            "plan_preview": "plan_preview",
            "complex_preview": "complex_preview",
            "log_hint": "log_hint",
        },
    )
    g.add_conditional_edges(
        "plan_preview",
        route_after_plan_preview,
        {"approval": "plan_approval", "end": END},
    )
    g.add_conditional_edges(
        "complex_preview",
        route_after_plan_preview,
        {"approval": "plan_approval", "end": END},
    )
    for n in ["safety", "boundary", "clarify", "rag", "personal", "plan_approval", "log_hint"]:
        g.add_edge(n, END)
    checkpointer = PostgresCheckpointSaver(session_factory)
    return g.compile(checkpointer=checkpointer)


def _session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def _run_graph_supersteps(
    graph: Any,
    input_: Any,
    config: dict[str, Any],
    *,
    task_id: str,
    cancel_checker: CancelCheckerFn | None,
) -> dict[str, Any]:
    """逐 super-step 流式执行图；每步之间做协作式取消检查。

    stream_mode="values" 产出与 ainvoke 等价的全量状态；interrupt/resume
    语义不变（interrupt 时流自然结束，由 aget_state 归一化结果）。
    """
    last: dict[str, Any] = {}
    async for chunk in graph.astream(input_, config, stream_mode="values"):
        last = chunk
        if cancel_checker is not None and await cancel_checker():
            emit_progress(
                stage="graph_cancelled",
                title="任务已取消",
                detail=f"task_id={task_id} 在 super-step 间检测到取消",
                tool="langgraph",
                status="done",
            )
            raise AgentTaskCancelledError(task_id)
    return last


async def run_fitness_agent(
    *,
    db: AsyncSession,
    user_id: int,
    message: str,
    task_id: str,
    session_id: str | None = None,
    trace_id: str | None = None,
    resume: bool = False,
    resume_command: dict[str, Any] | None = None,
    cancel_checker: CancelCheckerFn | None = None,
) -> FitnessAgentState:
    emit_progress(
        stage="graph_start",
        title="启动 Fitness Agent 状态图",
        detail=f"task_id={task_id} resume={resume} cmd={bool(resume_command)}",
        tool="langgraph",
    )
    factory = _session_factory()
    graph = build_fitness_graph(db, session_factory=factory)
    config = {"configurable": {"thread_id": task_id}}

    if resume_command is not None:
        emit_progress(stage="graph_resume", title="Command 恢复", detail="plan approval", tool="langgraph")
        raw = await _run_graph_supersteps(
            graph, Command(resume=resume_command), config, task_id=task_id, cancel_checker=cancel_checker
        )
    elif resume:
        emit_progress(stage="graph_resume", title="从检查点恢复", detail=f"thread_id={task_id}", tool="langgraph")
        raw = await _run_graph_supersteps(
            graph, None, config, task_id=task_id, cancel_checker=cancel_checker
        )
    else:
        prior = await load_latest_checkpoint_state(factory, task_id)
        init: FitnessAgentState = {
            "user_id": user_id,
            "session_id": session_id or "default",
            "task_id": task_id,
            "trace_id": trace_id or task_id,
            "original_request": message,
            "tool_results": [],
            "events": [{"event": "task_started", "task_id": task_id}],
            "retry_count": 0,
        }
        if prior:
            for k, v in prior.items():
                if k in {
                    "user_profile",
                    "workout_summary",
                    "diet_summary",
                    "intents",
                    "user_id",
                    "session_id",
                    "original_request",
                    "reply",
                    "final_status",
                    "pending_actions",
                    "retrieved_evidence",
                    "citations",
                }:
                    init[k] = v  # type: ignore[literal-required]
        raw = await _run_graph_supersteps(
            graph, init, config, task_id=task_id, cancel_checker=cancel_checker
        )

    snap = await graph.aget_state(config)
    result = normalize_graph_result(dict(raw), snap)
    result["task_id"] = task_id
    emit_progress(
        stage="graph_end",
        title="状态图执行结束",
        detail=f"final_status={result.get('final_status')} interrupted={result.get('interrupted')}",
        tool="langgraph",
        status="done",
    )
    return result  # type: ignore[return-value]
