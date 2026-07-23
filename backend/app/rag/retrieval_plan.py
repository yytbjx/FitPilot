"""动态检索策略 RetrievalPlan（增强方案 5.4）。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.rag import RetrievedChunk
from app.rag.query_understanding import analyze_query, analyze_query_async
from app.rag.retrieve import hybrid_retrieve


Strategy = Literal["simple_fact", "complex_explain", "high_risk", "personalized", "default"]


class RetrievalPlan(BaseModel):
    queries: list[str] = Field(default_factory=list)
    strategy: Strategy = "default"
    metadata_filters: dict[str, Any] = Field(default_factory=dict)
    top_k_dense: int = 8
    top_k_sparse: int = 8
    rerank_top_k: int = 4
    expand_parent: bool = True
    authority_threshold: int | None = None
    skip_rerank: bool = False
    query_understanding: dict[str, Any] = Field(default_factory=dict)


def build_retrieval_plan(query: str) -> RetrievalPlan:
    settings = get_settings()
    qinfo = analyze_query(query)
    qtype = str(qinfo.get("query_type") or "other")
    top_k = settings.rag_top_k
    rerank_k = settings.rag_rerank_top_k
    skip_rerank = bool(settings.rag_skip_rerank)
    authority: int | None = None
    expand = True
    strategy: Strategy = "default"
    filters: dict[str, Any] = {}

    if qtype == "risk" or qinfo.get("requires_authority"):
        strategy = "high_risk"
        top_k = min(top_k, 6)
        rerank_k = min(rerank_k, 3)
        authority = 2
        skip_rerank = False
        filters["doc_type"] = "safety"
    elif qtype == "personal":
        strategy = "personalized"
    elif qtype == "factoid":
        strategy = "simple_fact"
        top_k = min(5, top_k)
        rerank_k = min(3, rerank_k)
        skip_rerank = True
        expand = False
    elif qtype in {"why", "how_to", "comparison"} or qinfo.get("use_multi_query"):
        strategy = "complex_explain"
        top_k = max(top_k, 8)
        expand = True
        skip_rerank = False

    entities = qinfo.get("entities") or []
    if entities:
        filters["entities"] = entities

    return RetrievalPlan(
        queries=[qinfo.get("rewritten") or query],
        strategy=strategy,
        metadata_filters=filters,
        top_k_dense=top_k,
        top_k_sparse=top_k,
        rerank_top_k=rerank_k,
        expand_parent=expand,
        authority_threshold=authority,
        skip_rerank=skip_rerank,
        query_understanding=qinfo,
    )


async def retrieve_with_plan(plan: RetrievalPlan) -> list[RetrievedChunk]:
    """按 RetrievalPlan 执行检索（内部仍复用 hybrid_retrieve，并临时覆盖开关）。"""
    settings = get_settings()
    query = plan.queries[0] if plan.queries else ""
    qinfo = await analyze_query_async(query)
    plan.query_understanding = {**(plan.query_understanding or {}), **qinfo}
    if plan.strategy == "complex_explain" and qinfo.get("variants"):
        plan.queries = list(qinfo["variants"])[:3]
        query = plan.queries[0]

    old_skip = settings.rag_skip_rerank
    old_top = settings.rag_top_k
    old_rerank = settings.rag_rerank_top_k
    try:
        object.__setattr__(settings, "rag_skip_rerank", plan.skip_rerank)
        object.__setattr__(settings, "rag_top_k", plan.top_k_dense)
        object.__setattr__(settings, "rag_rerank_top_k", plan.rerank_top_k)
        chunks = await hybrid_retrieve(query, top_k=plan.top_k_dense)
    finally:
        object.__setattr__(settings, "rag_skip_rerank", old_skip)
        object.__setattr__(settings, "rag_top_k", old_top)
        object.__setattr__(settings, "rag_rerank_top_k", old_rerank)

    if plan.authority_threshold is not None:
        filtered = [
            c
            for c in chunks
            if int((c.metadata or {}).get("authority_level") or 0) >= plan.authority_threshold
        ]
        if filtered:
            chunks = filtered

    # 可选：按文档类型过滤（有字段时才生效）
    want_type = (plan.metadata_filters or {}).get("doc_type")
    if want_type:
        typed = [c for c in chunks if (c.metadata or {}).get("doc_type") == want_type]
        if typed:
            chunks = typed
    return chunks
