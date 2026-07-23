"""检索上下文拼装与多信号拒答判定（工程审查 P0）。"""

from __future__ import annotations

from typing import Any

from app.rag import RetrievedChunk
from app.rag.citations import map_citations


def _chunk_sources(chunks: list[RetrievedChunk]) -> set[str]:
    sources: set[str] = set()
    for c in chunks:
        src = (c.metadata or {}).get("retrieval_source")
        if src:
            for part in str(src).split("+"):
                if part:
                    sources.add(part)
    return sources


def build_context(
    chunks: list[RetrievedChunk],
    *,
    min_score: float = 0.01,
    min_hits: int = 1,
    rerank_min_score: float = -2.0,
    require_source_agreement: bool = False,
) -> dict[str, Any]:
    """组装生成上下文；证据不足时 no_answer=True，并返回细分 reason。"""
    usable = [c for c in chunks if c.text.strip()]
    if len(usable) < min_hits:
        return {
            "no_answer": True,
            "reason": "knowledge_not_found",
            "reason_detail": "NO_EVIDENCE",
            "context": "",
            "citations": [],
            "chunks": [],
            "answerability": {"signals": {"hit_count": len(usable)}},
        }

    top = usable[0]
    scores = [c.score for c in usable]
    dense_bm25_sources = _chunk_sources(usable)

    # CrossEncoder 分可能为负数；RRF 为正
    low_confidence = top.score < min_score and all(c.score <= 0 for c in usable)
    rerank_weak = top.score < rerank_min_score

    if low_confidence or rerank_weak:
        return {
            "no_answer": True,
            "reason": "knowledge_not_found",
            "reason_detail": "LOW_CONFIDENCE",
            "context": "",
            "citations": [],
            "chunks": [c.to_dict() for c in usable],
            "answerability": {
                "signals": {
                    "top_score": top.score,
                    "rerank_weak": rerank_weak,
                    "score_spread": max(scores) - min(scores) if scores else 0,
                }
            },
        }

    if require_source_agreement and len(dense_bm25_sources) < 2 and len(usable) >= 2:
        # 多路召回但仅单一路径命中，降低误答风险
        if top.score < 0.05:
            return {
                "no_answer": True,
                "reason": "conflicting_evidence",
                "reason_detail": "WEAK_MULTI_SOURCE",
                "context": "",
                "citations": [],
                "chunks": [c.to_dict() for c in usable],
                "answerability": {"signals": {"sources": list(dense_bm25_sources)}},
            }

    parts: list[str] = []
    usable_for_cite = usable
    for i, c in enumerate(usable_for_cite, start=1):
        parts.append(f"[{i}] {c.citation}\n{c.text}")
    citations = map_citations(usable_for_cite)
    return {
        "no_answer": False,
        "reason": None,
        "reason_detail": None,
        "context": "\n\n".join(parts),
        "citations": citations,
        "chunks": [c.to_dict() for c in usable],
        "answerability": {
            "signals": {
                "top_score": top.score,
                "hit_count": len(usable),
                "sources": list(dense_bm25_sources),
            }
        },
    }
