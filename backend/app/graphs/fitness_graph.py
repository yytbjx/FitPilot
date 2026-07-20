"""LangGraph 健身 Agent 主图（实时进度推送）。"""

from __future__ import annotations

import re
from typing import Any, Literal

from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.progress import emit_progress
from app.db.session import get_engine
from app.graphs.checkpointer import PostgresCheckpointSaver, load_latest_checkpoint_state
from app.graphs.runner_utils import normalize_graph_result
from app.graphs.state import FitnessAgentState
from app.rag.context import build_context
from app.rag.retrieve import hybrid_retrieve
from app.services.ollama_client import get_ollama_client
from app.tools.domain import (
    check_risk,
    commit_plans,
    get_user_profile_data,
    preview_and_stage_plans,
    recent_logs,
    weekly_adjust_preview,
)

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
}


def classify_intent(text: str) -> Intent:
    t = text or ""
    risk = check_risk(t)
    if risk["risk_level"] == "high":
        return "risk_or_medical"
    # 明确超出健身助手边界（先于知识问答，避免误入 RAG）
    if re.search(r"(写代码|写.*代码|股票|炒股|比特币|加密货币|算命|占卜)", t):
        return "unsupported"
    if re.search(
        r"(计划|安排训练|生成计划|调整计划|换个饮食|调整饮食|调整训练|调整.*训练|调整.*饮食)",
        t,
    ):
        if "调整" in t:
            return "plan_adjust"
        return "plan_create"
    if re.search(r"(我练了|打卡训练|记录训练)", t):
        return "workout_log_write"
    if re.search(r"(我吃了|记录饮食|打卡饮食)", t):
        return "diet_log_write"
    if re.search(r"(我的档案|我的体重|我的记录|本周训练|营养目标)", t):
        return "personal_data_query"
    if re.search(r"(蛋白|减脂|增肌|热量|深蹲|硬拉|食谱|怎么|如何|什么|知识)", t):
        return "knowledge_query"
    if re.search(r"(你好|您好|谢谢|哈哈)", t):
        return "small_talk"
    return "knowledge_query"


def _intent_confident(text: str) -> bool:
    """规则是否命中明确模式（未命中则默认为 knowledge_query，可选用小模型辅助）。"""
    t = text or ""
    risk = check_risk(t)
    if risk["risk_level"] == "high":
        return True
    patterns = [
        r"(写代码|写.*代码|股票|炒股|比特币|加密货币|算命|占卜)",
        r"(计划|安排训练|生成计划|调整计划|换个饮食|调整饮食|调整训练|调整.*训练|调整.*饮食)",
        r"(我练了|打卡训练|记录训练)",
        r"(我吃了|记录饮食|打卡饮食)",
        r"(我的档案|我的体重|我的记录|本周训练|营养目标)",
        r"(蛋白|减脂|增肌|热量|深蹲|硬拉|食谱|怎么|如何|什么|知识)",
        r"(你好|您好|谢谢|哈哈)",
    ]
    return any(re.search(p, t) for p in patterns)


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


async def node_safety(state: FitnessAgentState) -> dict[str, Any]:
    emit_progress(
        stage="safety",
        title="安全节点",
        detail="阻断自动增强训练，返回就医建议",
        tool="check_risk",
        status="done",
    )
    msg = (
        "检测到可能与伤病/医疗相关的高风险表述。"
        "FitPilot 不能提供诊断或治疗建议，也不会自动增强训练计划。请尽快咨询医生。"
    )
    return {
        "reply": msg,
        "final_status": "blocked_safety",
        "requires_confirmation": False,
        "events": [{"event": "completed", "status": "blocked_safety"}],
    }


async def node_boundary(state: FitnessAgentState) -> dict[str, Any]:
    emit_progress(stage="boundary", title="边界说明", detail="闲聊/能力边界回复", status="done")
    return {
        "reply": "我是 FitPilot 健身与膳食助手。可以问营养/训练知识，或让我生成计划预览。",
        "final_status": "completed",
        "events": [{"event": "completed", "status": "small_talk"}],
    }


async def node_rag(state: FitnessAgentState) -> dict[str, Any]:
    query = state.get("original_request", "")
    settings = get_settings()
    emit_progress(
        stage="rag",
        title="进入 RAG 知识节点",
        detail="混合检索 → 证据拼装 → Ollama 生成",
        tool="hybrid_retrieve",
    )
    chunks = await hybrid_retrieve(query)
    emit_progress(
        stage="rag_context",
        title="拼装生成上下文",
        detail=f"证据条数={len(chunks)}",
        tool="build_context",
    )
    packed = build_context(chunks)
    if packed["no_answer"]:
        emit_progress(
            stage="rag_context",
            title="证据不足，拒答",
            detail=str(packed.get("reason")),
            tool="build_context",
            status="done",
        )
        reply = (
            "根据当前知识库，我无法给出有足够证据支持的答案（"
            f"{packed.get('reason') or packed.get('reason_detail')}）。请换个问法，或先入库相关资料。"
        )
        return {
            "reply": reply,
            "retrieved_evidence": [],
            "citations": [],
            "final_status": "no_answer",
            "events": [{"event": "completed", "status": "no_answer", "reason": packed.get("reason")}],
            "tool_results": [{"tool": "hybrid_retrieve", "result": packed}],
        }

    rag_model = settings.resolve_ollama_model("rag")
    emit_progress(
        stage="llm_generate",
        title="调用 Ollama 生成回答",
        detail=(
            f"角色=rag 模型={rag_model} @ {settings.ollama_base_url}；"
            f"keep_alive={settings.ollama_keep_alive}"
        ),
        tool="ollama.chat",
    )
    system = (
        "你是 FitPilot 助手。仅依据给定证据回答，列出引用编号。"
        "不做疾病诊断。若证据不足请明确说不知道。请用简洁中文。"
    )
    user = f"问题：{query}\n\n证据：\n{packed['context']}\n\n请用中文简洁回答并标注引用编号。"
    result = await get_ollama_client().chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        role="rag",
        # 生成略短一些，降低 1.5B/4B 延迟与显存峰值
        options={"num_predict": 512, "temperature": 0.3},
    )
    reply = (result.get("message") or {}).get("content") or ""
    emit_progress(
        stage="llm_generate",
        title="LLM 生成完成",
        detail=f"回复长度={len(reply)} 字",
        tool="ollama.chat",
        status="done",
    )
    return {
        "reply": reply,
        "retrieved_evidence": packed.get("chunks") or [],
        "citations": packed.get("citations") or [],
        "final_status": "completed",
        "events": [{"event": "completed", "status": "knowledge_answer"}],
        "tool_results": [{"tool": "hybrid_retrieve", "result": {"citations": packed.get("citations")}}],
    }


async def node_personal(state: FitnessAgentState, *, db: AsyncSession) -> dict[str, Any]:
    emit_progress(
        stage="personal",
        title="读取个人档案与近期记录",
        detail="工具：get_user_profile_data / recent_logs",
        tool="get_user_profile_data",
    )
    profile = await get_user_profile_data(db, state["user_id"])
    emit_progress(
        stage="personal",
        title="汇总训练/饮食数据",
        detail="确定性营养与容量计算",
        tool="recent_logs",
    )
    logs = await recent_logs(db, state["user_id"])
    targets = (profile.get("nutrition_estimate") or {}).get("targets") or {}
    reply = (
        f"档案目标：{profile.get('goal') or '未设置'}；体重 {profile.get('weight_kg') or '-'} kg。\n"
        f"近 7 天训练次数 {logs['workout_count']}，饮食热量合计 {logs['diet_kcal']} kcal，"
        f"蛋白 {logs['diet_protein_g']} g。\n"
        f"规则估算目标：{targets or '请完善身高体重年龄后查看'}。"
    )
    emit_progress(stage="personal", title="个人数据汇总完成", status="done", tool="recent_logs")
    return {
        "user_profile": profile,
        "workout_summary": logs.get("volume") or {},
        "diet_summary": {"kcal": logs["diet_kcal"], "protein_g": logs["diet_protein_g"]},
        "body_trend": {"items": logs.get("body_metrics") or []},
        "reply": reply,
        "final_status": "completed",
        "events": [{"event": "completed", "status": "personal_data"}],
        "tool_results": [
            {"tool": "get_user_profile_data", "result": profile},
            {"tool": "recent_logs", "result": logs},
        ],
    }


async def node_plan_preview(state: FitnessAgentState, *, db: AsyncSession) -> dict[str, Any]:
    """生成计划预览（不中断）。"""
    if state.get("risk_level") == "high":
        return await node_safety(state)
    emit_progress(
        stage="plan",
        title="生成计划预览",
        detail="工具：preview_and_stage_plans / validate_constraints",
        tool="preview_and_stage_plans",
    )
    profile = state.get("user_profile") or await get_user_profile_data(db, state["user_id"])
    staged = await preview_and_stage_plans(db, state["user_id"], profile, request_id=state.get("trace_id"))
    if not staged.get("ok"):
        emit_progress(
            stage="plan",
            title="计划校验失败",
            detail="；".join(staged.get("validation", {}).get("errors") or []),
            tool="validate_constraints",
            status="error",
        )
        return {
            "reply": "计划未通过约束校验：" + "；".join(staged.get("validation", {}).get("errors") or []),
            "final_status": "validation_failed",
            "user_profile": profile,
            "events": [{"event": "failed", "status": "validation_failed"}],
            "tool_results": [{"tool": "preview_and_stage_plans", "result": staged}],
        }
    pending = staged["pending"]
    return {
        "user_profile": profile,
        "pending_actions": pending,
        "reply": "已生成训练+饮食计划预览，请确认后再写入正式版本。",
        "tool_results": [{"tool": "preview_and_stage_plans", "result": staged}],
        "events": [
            {
                "event": "approval_required",
                "plan_id": pending["workout_plan_id"],
                "workout_plan_id": pending["workout_plan_id"],
                "diet_plan_id": pending["diet_plan_id"],
                "preview": pending["preview"],
                "diff": pending.get("diff"),
                "task_id": state.get("task_id"),
            }
        ],
    }


def _interrupt_payload(pending: dict[str, Any], *, weekly_reason: str | None = None) -> dict[str, Any]:
    return {
        "type": "plan_approval",
        "workout_plan_id": pending.get("workout_plan_id"),
        "plan_id": pending.get("workout_plan_id"),
        "diet_plan_id": pending.get("diet_plan_id"),
        "preview": pending.get("preview"),
        "diff": pending.get("diff"),
        "weekly_reason": weekly_reason or pending.get("weekly_reason"),
    }


async def node_plan_confirm(state: FitnessAgentState) -> dict[str, Any]:
    """LangGraph interrupt：等待人工批准计划。"""
    pending = state.get("pending_actions") or {}
    emit_progress(
        stage="plan_confirm",
        title="等待用户确认",
        detail="LangGraph interrupt 已触发",
        tool="interrupt",
        status="done",
    )
    raw = interrupt(_interrupt_payload(pending))
    decision = raw if isinstance(raw, dict) else {"approve": bool(raw)}
    return {
        "approval_decision": decision,
        "requires_confirmation": False,
        "events": [{"event": "approval_decision", "decision": decision}],
    }


def route_plan_confirm(state: FitnessAgentState) -> str:
    decision = state.get("approval_decision") or {}
    return "commit" if decision.get("approve") else "reject"


async def node_plan_commit(state: FitnessAgentState, *, db: AsyncSession) -> dict[str, Any]:
    pending = state.get("pending_actions") or {}
    result = await commit_plans(db, state["user_id"], pending)
    comment = (state.get("approval_decision") or {}).get("comment")
    msg = "计划已批准并写入正式版本。"
    if comment:
        msg += f"（备注：{comment}）"
    return {
        "reply": msg,
        "final_status": "completed",
        "pending_actions": None,
        "events": [{"event": "completed", "status": "plan_committed", **result}],
        "tool_results": [{"tool": "commit_plans", "result": result}],
    }


async def node_plan_reject(state: FitnessAgentState) -> dict[str, Any]:
    comment = (state.get("approval_decision") or {}).get("comment")
    msg = "已取消计划写入，预览保持草稿状态。"
    if comment:
        msg += f"（备注：{comment}）"
    return {
        "reply": msg,
        "final_status": "rejected",
        "pending_actions": None,
        "events": [{"event": "completed", "status": "plan_rejected"}],
    }


async def node_complex_plan_preview(state: FitnessAgentState, *, db: AsyncSession) -> dict[str, Any]:
    """复杂计划：档案 → 日志 → 周联合调整预览。"""
    if state.get("risk_level") == "high":
        return await node_safety(state)

    profile = await get_user_profile_data(db, state["user_id"])
    emit_progress(stage="complex_profile", title="读取档案", tool="get_user_profile_data", status="done")
    logs = await recent_logs(db, state["user_id"])
    emit_progress(stage="complex_logs", title="汇总近期训练与饮食", tool="recent_logs", status="done")
    staged = await weekly_adjust_preview(db, state["user_id"], profile, request_id=state.get("trace_id"))
    tool_results = [
        {"tool": "get_user_profile_data", "result": profile},
        {"tool": "recent_logs", "result": logs},
        {"tool": "weekly_adjust_preview", "result": staged},
    ]
    if not staged.get("ok"):
        return {
            "reply": "计划未通过约束校验：" + "；".join(
                staged.get("validation", {}).get("errors") or []
            ),
            "final_status": "validation_failed",
            "user_profile": profile,
            "tool_results": tool_results,
            "events": [{"event": "failed", "status": "validation_failed"}],
        }
    pending = staged["pending"]
    diag = [
        f"近7天训练{logs.get('workout_count')}次",
        f"饮食合计{logs.get('diet_kcal')}kcal",
    ]
    if pending.get("weekly_reason"):
        diag.append(str(pending["weekly_reason"]))
    return {
        "user_profile": profile,
        "workout_summary": logs.get("volume") or {},
        "diet_summary": {"kcal": logs.get("diet_kcal"), "protein_g": logs.get("diet_protein_g")},
        "pending_actions": pending,
        "reply": "已根据近期数据生成训练+饮食调整预览，请查看差异后确认。"
        + f"（{'；'.join(diag)}）",
        "tool_results": tool_results,
        "events": [
            {
                "event": "approval_required",
                "plan_id": pending["workout_plan_id"],
                "workout_plan_id": pending["workout_plan_id"],
                "diet_plan_id": pending["diet_plan_id"],
                "preview": pending["preview"],
                "diff": pending.get("diff"),
                "weekly_reason": pending.get("weekly_reason"),
                "task_id": state.get("task_id"),
            }
        ],
    }


async def node_log_hint(state: FitnessAgentState) -> dict[str, Any]:
    emit_progress(
        stage="log_hint",
        title="引导去记录页",
        detail="不在对话中直接写库",
        status="done",
    )
    return {
        "reply": "请在「今日记录」页面录入训练/饮食（数值由食物库确定性计算）。此处仅引导，不直接写库。",
        "final_status": "completed",
        "events": [{"event": "completed", "status": "log_hint"}],
    }


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
    # validation_failed 时直接结束
    if state.get("final_status") in {"validation_failed", "blocked_safety", "no_answer"}:
        return "end"
    return "confirm"


def route_after_classify(state: FitnessAgentState) -> str:
    intent = (state.get("intents") or ["unsupported"])[0]
    if intent == "risk_or_medical":
        return "safety"
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
    if session_factory is None:
        session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async def personal_wrapper(state: FitnessAgentState) -> dict[str, Any]:
        return await node_personal(state, db=db)

    async def plan_preview_wrapper(state: FitnessAgentState) -> dict[str, Any]:
        return await node_plan_preview(state, db=db)

    async def complex_preview_wrapper(state: FitnessAgentState) -> dict[str, Any]:
        return await node_complex_plan_preview(state, db=db)

    async def plan_commit_wrapper(state: FitnessAgentState) -> dict[str, Any]:
        return await node_plan_commit(state, db=db)

    g = StateGraph(FitnessAgentState)
    g.add_node("classify", node_classify)
    g.add_node("safety", node_safety)
    g.add_node("boundary", node_boundary)
    g.add_node("rag", node_rag)
    g.add_node("personal", personal_wrapper)
    g.add_node("plan_preview", plan_preview_wrapper)
    g.add_node("complex_preview", complex_preview_wrapper)
    g.add_node("plan_confirm", node_plan_confirm)
    g.add_node("plan_commit", plan_commit_wrapper)
    g.add_node("plan_reject", node_plan_reject)
    g.add_node("log_hint", node_log_hint)
    g.set_entry_point("classify")
    g.add_conditional_edges(
        "classify",
        route_after_classify,
        {
            "safety": "safety",
            "boundary": "boundary",
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
        {"confirm": "plan_confirm", "end": END},
    )
    g.add_conditional_edges(
        "complex_preview",
        route_after_plan_preview,
        {"confirm": "plan_confirm", "end": END},
    )
    g.add_conditional_edges(
        "plan_confirm",
        route_plan_confirm,
        {"commit": "plan_commit", "reject": "plan_reject"},
    )
    for n in ["safety", "boundary", "rag", "personal", "plan_commit", "plan_reject", "log_hint"]:
        g.add_edge(n, END)
    checkpointer = PostgresCheckpointSaver(session_factory)
    return g.compile(checkpointer=checkpointer)


def _session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


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
        raw = await graph.ainvoke(Command(resume=resume_command), config)
    elif resume:
        emit_progress(stage="graph_resume", title="从检查点恢复", detail=f"thread_id={task_id}", tool="langgraph")
        raw = await graph.ainvoke(None, config)
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
        raw = await graph.ainvoke(init, config)

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
