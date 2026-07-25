"""检索上下文拼装；拒答判定复用 Evidence Gate 单套逻辑（迭代 3 收敛）。

历史说明：迭代 3 前本模块维护第二套拒答条件（top_score<-2.0 等），与
`evidence_gate.assess_evidence`（confidence>=0.35）并存且口径不一致。现已收敛：
build_context 的拒答判定委托给 assess_evidence，本模块只保留上下文拼装与
多路召回一致性（require_source_agreement）附加检查。返回结构保持不变。
"""

from __future__ import annotations

from typing import Any

from app.rag import RetrievedChunk
from app.rag.citations import map_citations
from app.rag.evidence_gate import assess_evidence, score_scale_of


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
    """组装生成上下文；证据不足时 no_answer=True，并返回细分 reason。

    拒答判定复用 assess_evidence（min_score → min_top_score，rerank_min_score
    仅对 rerank 分体系生效）；参数签名与返回字段保持兼容。
    """
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
    scale = score_scale_of(scores)

    assessment = assess_evidence(
        usable,
        min_hits=1,
        min_top_score=min_score,
        rerank_min_score=rerank_min_score,
    )

    if not assessment.answerable:
        return {
            "no_answer": True,
            "reason": (
                "conflicting_evidence" if assessment.conflicts else "knowledge_not_found"
            ),
            "reason_detail": assessment.reason or "WEAK_EVIDENCE",
            "context": "",
            "citations": [],
            "chunks": [c.to_dict() for c in usable],
            "answerability": {
                "signals": {
                    "top_score": top.score,
                    "rerank_weak": bool(scale == "rerank" and top.score < rerank_min_score),
                    "score_spread": max(scores) - min(scores) if scores else 0,
                    "confidence": assessment.confidence,
                    "score_scale": scale,
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
                "confidence": assessment.confidence,
                "score_scale": scale,
            }
        },
    }
