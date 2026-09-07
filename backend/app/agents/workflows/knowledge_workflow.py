"""知识问答领域工作流（KV Cache 友好装配 + 分层记忆召回）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.context_assembly import assemble_context
from app.core.config import get_settings
from app.core.progress import emit_progress
from app.db.session import get_engine
from app.graphs.state import FitnessAgentState
from app.rag.citations import citation_coverage, map_citations
from app.rag.context import build_context
from app.rag.evidence_gate import assess_evidence
from app.rag.retrieval_plan import build_retrieval_plan, retrieve_with_plan
from app.services.ollama_client import get_ollama_client


async def _load_memory_assembly(
    state: FitnessAgentState,
    *,
    query: str,
    evidence: str,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """召回会话记忆并用稳定前缀策略装配；失败时回退到无记忆装配。"""
    settings = get_settings()
    user_id = state.get("user_id")
    session_id = state.get("session_id") or "default"
    if not settings.conversation_memory_enabled or not session_id:
        assembled = assemble_context(
            query=query,
            core=[],
            recall_candidates=[],
            evidence=evidence,
            user_id=user_id,
            token_budget=settings.context_token_budget,
        )
        return assembled.messages, assembled.to_metrics()

    from app.agents.memory.conversation_memory import build_context_bundle

    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    try:
        async with factory() as db:
            bundle = await build_context_bundle(db, session_id=session_id, query=query)
        candidates = [*bundle.recalled, *bundle.neighbors]
        assembled = assemble_context(
            query=query,
            core=bundle.core,
            recall_candidates=candidates,
            evidence=evidence,
            user_id=user_id,
            token_budget=settings.context_token_budget,
            state_note=f"archival_turns={bundle.archival_count}",
        )
        metrics = assembled.to_metrics()
        metrics["archival_count"] = bundle.archival_count
        metrics["core_turns"] = [f.turn_index for f in bundle.core]
        metrics["recall_hits"] = len(bundle.recalled)
        return assembled.messages, metrics
    except Exception as exc:  # noqa: BLE001 — 记忆失败不阻断知识问答
        emit_progress(
            stage="context_assembly",
            title="会话记忆装配回退",
            detail=str(exc)[:200],
            tool="conversation_memory",
            status="done",
        )
        assembled = assemble_context(
            query=query,
            core=[],
            recall_candidates=[],
            evidence=evidence,
            user_id=user_id,
            token_budget=settings.context_token_budget,
        )
        return assembled.messages, {**assembled.to_metrics(), "fallback": True, "error": str(exc)[:200]}


async def run_knowledge_workflow(state: FitnessAgentState) -> dict[str, Any]:
    query = state.get("original_request", "")
    settings = get_settings()
    plan = build_retrieval_plan(query)
    emit_progress(
        stage="knowledge_workflow",
        title="知识子图：动态检索",
        detail=f"strategy={plan.strategy} top_k={plan.top_k_dense}",
        tool="retrieve_with_plan",
        extra=plan.model_dump(),
    )
    chunks = await retrieve_with_plan(plan)
    assessment = assess_evidence(
        chunks,
        query=query,
        authority_threshold=plan.authority_threshold,
    )
    emit_progress(
        stage="rag_evidence_gate",
        title="Evidence Gate",
        detail=(
            f"answerable={assessment.answerable} confidence={assessment.confidence} "
            f"reason={assessment.reason}"
        ),
        tool="assess_evidence",
        status="done",
        extra=assessment.model_dump(),
    )
    packed = build_context(chunks)
    if (not assessment.answerable) or packed["no_answer"]:
        reason = assessment.reason or packed.get("reason") or packed.get("reason_detail")
        reply = (
            "根据当前知识库，我无法给出有足够证据支持的答案（"
            f"{reason}）。请换个问法，或先入库相关资料。"
        )
        return {
            "reply": reply,
            "retrieved_evidence": assessment.selected_evidence,
            "citations": [],
            "final_status": "no_answer",
            "events": [
                {
                    "event": "completed",
                    "status": "no_answer",
                    "reason": reason,
                    "evidence_assessment": assessment.model_dump(),
                    "retrieval_plan": plan.model_dump(),
                }
            ],
            "tool_results": [
                {"tool": "retrieve_with_plan", "result": packed},
                {"tool": "assess_evidence", "result": assessment.model_dump()},
            ],
        }

    rag_model = settings.resolve_ollama_model("rag")
    emit_progress(
        stage="context_assembly",
        title="KV Cache 友好上下文装配",
        detail=f"budget={settings.context_token_budget}",
        tool="assemble_context",
    )
    messages, ctx_metrics = await _load_memory_assembly(
        state, query=query, evidence=str(packed.get("context") or "")
    )
    emit_progress(
        stage="context_assembly",
        title="装配完成",
        detail=(
            f"tokens={ctx_metrics.get('total_tokens')} "
            f"reduction={ctx_metrics.get('reduction_ratio')} "
            f"lcp={ctx_metrics.get('lcp_ratio')}"
        ),
        tool="assemble_context",
        status="done",
        extra=ctx_metrics,
    )
    emit_progress(
        stage="llm_generate",
        title="调用 Ollama 生成回答",
        detail=f"角色=rag 模型={rag_model}",
        tool="ollama.chat",
    )
    # 稳定 system 前缀来自装配；若装配异常回退旧提示
    if not messages or messages[0].get("role") != "system":
        system = (
            "你是 FitPilot 助手。仅依据给定证据回答，列出引用编号。"
            "不做疾病诊断。若证据不足请明确说不知道。请用简洁中文。"
        )
        user = f"问题：{query}\n\n证据：\n{packed['context']}\n\n请用中文简洁回答并标注引用编号。"
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    else:
        # 在 user 末尾追加引用要求（动态后置，不改稳定前缀）
        messages = [
            messages[0],
            {
                "role": "user",
                "content": (messages[1]["content"] if len(messages) > 1 else "")
                + "\n\n请用中文简洁回答并标注引用编号。",
            },
        ]

    result = await get_ollama_client().chat(
        messages,
        role="rag",
        options={"num_predict": 512, "temperature": 0.3},
    )
    reply = (result.get("message") or {}).get("content") or ""
    emit_progress(stage="llm_generate", title="LLM 生成完成", detail=f"回复长度={len(reply)} 字", status="done")
    evidence_chunks = chunks if chunks else []
    from app.rag import RetrievedChunk

    mapped_chunks: list[RetrievedChunk] = []
    for raw in packed.get("chunks") or []:
        if isinstance(raw, dict):
            mapped_chunks.append(
                RetrievedChunk(
                    chunk_id=str(raw.get("chunk_id") or ""),
                    text=str(raw.get("text") or ""),
                    score=float(raw.get("score") or 0),
                    title=str(raw.get("title") or ""),
                    section_path=str(raw.get("section_path") or ""),
                    source_path=str(raw.get("source_path") or ""),
                    document_id=str(raw.get("document_id") or ""),
                    version_id=str(raw.get("version_id") or ""),
                    citation=str(raw.get("citation") or ""),
                    metadata=dict(raw.get("metadata") or {}),
                )
            )
    citations = map_citations(mapped_chunks or evidence_chunks, answer_text=reply)
    coverage = citation_coverage(citations)
    return {
        "reply": reply,
        "retrieved_evidence": packed.get("chunks") or [],
        "citations": citations,
        "final_status": "completed",
        "context_metrics": ctx_metrics,
        "events": [
            {
                "event": "completed",
                "status": "knowledge_answer",
                "evidence_assessment": assessment.model_dump(),
                "retrieval_plan": plan.model_dump(),
                "citation_coverage": coverage,
                "context_metrics": ctx_metrics,
            }
        ],
        "tool_results": [
            {
                "tool": "retrieve_with_plan",
                "result": {
                    "citations": citations,
                    "plan": plan.model_dump(),
                    "citation_coverage": coverage,
                },
            },
            {"tool": "assess_evidence", "result": assessment.model_dump()},
            {"tool": "assemble_context", "result": ctx_metrics},
        ],
    }
