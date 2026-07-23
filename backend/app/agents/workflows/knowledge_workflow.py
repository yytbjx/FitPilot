"""知识问答领域工作流。"""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.core.progress import emit_progress
from app.graphs.state import FitnessAgentState
from app.rag.citations import citation_coverage, map_citations
from app.rag.context import build_context
from app.rag.evidence_gate import assess_evidence
from app.rag.retrieval_plan import build_retrieval_plan, retrieve_with_plan
from app.services.ollama_client import get_ollama_client


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
        stage="llm_generate",
        title="调用 Ollama 生成回答",
        detail=f"角色=rag 模型={rag_model}",
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
        options={"num_predict": 512, "temperature": 0.3},
    )
    reply = (result.get("message") or {}).get("content") or ""
    emit_progress(stage="llm_generate", title="LLM 生成完成", detail=f"回复长度={len(reply)} 字", status="done")
    evidence_chunks = chunks if chunks else []
    # 优先用 packed 中的检索块顺序映射引用
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
        "events": [
            {
                "event": "completed",
                "status": "knowledge_answer",
                "evidence_assessment": assessment.model_dump(),
                "retrieval_plan": plan.model_dump(),
                "citation_coverage": coverage,
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
        ],
    }
