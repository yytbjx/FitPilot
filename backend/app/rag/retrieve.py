"""混合检索：Dense + BM25 + RRF + Rerank（带实时进度）。"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from functools import partial

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import RETRIEVAL_COUNT, RETRIEVAL_LATENCY, timed_histogram
from app.core.progress import emit_progress
from app.core.tracing import add_step, finish_step
from app.rag import RetrievedChunk
from app.rag.bm25 import get_bm25_index
from app.rag.embeddings import embed_query
from app.rag.parent_child import expand_child_to_parent
from app.rag.query_understanding import analyze_query_async
from app.rag.rerank import rerank
from app.services.qdrant_client import get_qdrant_service

logger = get_logger(__name__)


def rrf_fuse(
    ranked_lists: list[list[tuple[str, float]]], *, k: int = 60
) -> list[tuple[str, float]]:
    scores: dict[str, float] = defaultdict(float)
    for ranked in ranked_lists:
        for rank, (doc_id, _) in enumerate(ranked, start=1):
            scores[doc_id] += 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


async def dense_search(query: str, top_k: int) -> list[tuple[str, float, dict]]:
    settings = get_settings()
    emit_progress(
        stage="rag_dense_embed",
        title="Dense 向量化查询",
        detail=f"Embedding 设备={settings.embedding_device}，模型={settings.embedding_model}",
        tool="embed_query",
    )
    # model.encode 为同步阻塞调用，放线程池避免阻塞事件循环
    vector = await asyncio.to_thread(embed_query, query)
    emit_progress(
        stage="rag_dense_search",
        title="Qdrant Dense 检索",
        detail=f"集合={settings.qdrant_collection}，top_k={top_k}",
        tool="qdrant.search",
    )
    client = get_qdrant_service().client
    try:
        if hasattr(client, "query_points"):
            res = client.query_points(
                collection_name=settings.qdrant_collection,
                query=vector,
                limit=top_k,
                with_payload=True,
            )
            points = res.points
        else:
            points = client.search(
                collection_name=settings.qdrant_collection,
                query_vector=vector,
                limit=top_k,
                with_payload=True,
            )
    except Exception as exc:
        logger.warning("dense_search_failed", error=str(exc))
        emit_progress(
            stage="rag_dense_search",
            title="Dense 检索失败",
            detail=str(exc),
            tool="qdrant.search",
            status="error",
        )
        return []

    out: list[tuple[str, float, dict]] = []
    for p in points:
        payload = dict(p.payload or {})
        cid = str(payload.get("chunk_id") or p.id)
        out.append((cid, float(p.score or 0.0), payload))
    emit_progress(
        stage="rag_dense_search",
        title="Dense 检索完成",
        detail=f"召回 {len(out)} 条",
        tool="qdrant.search",
        status="done",
    )
    return out


def bm25_search(query: str, top_k: int) -> list[tuple[str, float, dict]]:
    emit_progress(
        stage="rag_bm25",
        title="BM25 稀疏检索",
        detail=f"top_k={top_k}",
        tool="bm25.search",
    )
    index = get_bm25_index()
    hits = index.search(query, top_k=top_k)
    out: list[tuple[str, float, dict]] = []
    for cid, score in hits:
        payload = index.payloads.get(cid, {})
        out.append((cid, score, payload))
    emit_progress(
        stage="rag_bm25",
        title="BM25 检索完成",
        detail=f"召回 {len(out)} 条",
        tool="bm25.search",
        status="done",
    )
    return out


async def hybrid_retrieve(
    query: str,
    top_k: int | None = None,
    *,
    rerank_top_k: int | None = None,
    skip_rerank: bool | None = None,
) -> list[RetrievedChunk]:
    """混合检索入口。

    top_k / rerank_top_k / skip_rerank 均为显式参数；传 None 时回退到全局 settings。
    调用方不得再临时修改全局 settings 单例（并发污染）。
    """
    settings = get_settings()
    top_k = top_k or settings.rag_top_k
    rerank_k = rerank_top_k or settings.rag_rerank_top_k
    skip_rerank = settings.rag_skip_rerank if skip_rerank is None else skip_rerank
    qinfo = await analyze_query_async(query)
    queries = qinfo["variants"] if qinfo.get("use_multi_query") else [qinfo["rewritten"]]
    step = add_step("hybrid_retrieve", "混合检索", detail=" | ".join(queries)[:120])
    RETRIEVAL_COUNT.labels(stage="hybrid").inc()

    with timed_histogram(RETRIEVAL_LATENCY, stage="hybrid"):
        emit_progress(
            stage="rag_hybrid",
            title="开始混合检索",
            detail=f"Multi-Query={len(queries)}：Dense ∥ BM25 → RRF → Rerank",
            tool="hybrid_retrieve",
        )

        dense_all: list[tuple[str, float, dict]] = []
        sparse_all: list[tuple[str, float, dict]] = []
        for q in queries:
            dense_all.extend(await dense_search(q, top_k))
            sparse_all.extend(bm25_search(q, top_k))
        dense = dense_all
        sparse = sparse_all
        dense_ids = {d[0] for d in dense}
        sparse_ids = {s[0] for s in sparse}

        emit_progress(
            stage="rag_rrf",
            title="RRF 融合排序",
            detail=f"Dense={len(dense)}，BM25={len(sparse)}",
            tool="rrf_fuse",
        )
        fused_ids = rrf_fuse(
            [[(d[0], d[1]) for d in dense], [(s[0], s[1]) for s in sparse]]
        )
        payload_map: dict[str, dict] = {}
        for cid, score, payload in dense + sparse:
            if cid not in payload_map:
                payload_map[cid] = {**payload, "_score": score}

        candidates: list[RetrievedChunk] = []
        for cid, fused in fused_ids[: max(top_k * 2, 10)]:
            p = expand_child_to_parent(payload_map.get(cid, {}))
            text = str(p.get("text") or "")
            if not text:
                continue
            sources = []
            if cid in dense_ids:
                sources.append("dense")
            if cid in sparse_ids:
                sources.append("bm25")
            candidates.append(
                RetrievedChunk(
                    chunk_id=cid,
                    text=text,
                    score=float(fused),
                    title=str(p.get("title") or ""),
                    section_path=str(p.get("section_path") or ""),
                    source_path=str(p.get("source_path") or ""),
                    document_id=str(p.get("document_id") or ""),
                    version_id=str(p.get("version_id") or ""),
                    metadata={"retrieval_source": "+".join(sources) or "unknown"},
                )
            )

        dedup: dict[str, RetrievedChunk] = {}
        for c in candidates:
            key = f"{c.document_id}|{c.section_path}|{c.text[:80]}"
            if key not in dedup or c.score > dedup[key].score:
                dedup[key] = c
        candidates = sorted(dedup.values(), key=lambda x: x.score, reverse=True)[: top_k * 2]

        if skip_rerank:
            emit_progress(
                stage="rag_rerank",
                title="跳过 Reranker",
                detail=f"skip_rerank=true；直接取 RRF 前 {rerank_k} 条",
                tool="rerank",
                status="done",
            )
            final = candidates[:rerank_k]
            for c in final:
                c.citation = f"{c.title or c.document_id}#{c.section_path or 'body'}@{c.version_id}"
            finish_step(step, detail=f"hits={len(final)} skip_rerank=1")
            return final

        emit_progress(
            stage="rag_rerank",
            title="Reranker 精排",
            detail=(
                f"候选 {len(candidates)} → top {rerank_k}；"
                f"设备={settings.reranker_device}；模型={settings.reranker_model}"
            ),
            tool="rerank",
        )
        # CrossEncoder.predict 为同步阻塞调用，放线程池执行
        ranked = await asyncio.to_thread(
            partial(rerank, query, [c.text for c in candidates], top_k=rerank_k)
        )
        final = []
        for idx, score in ranked:
            c = candidates[idx]
            c.score = score
            c.citation = f"{c.title or c.document_id}#{c.section_path or 'body'}@{c.version_id}"
            final.append(c)
        emit_progress(
            stage="rag_rerank",
            title="精排完成",
            detail=f"保留 {len(final)} 条证据",
            tool="rerank",
            status="done",
            extra={"citations": [c.citation for c in final]},
        )
        finish_step(step, detail=f"hits={len(final)}")
        return final
