"""Reranker 懒加载。"""

from __future__ import annotations

import os

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
_reranker = None


def get_reranker():
    global _reranker
    if os.environ.get("RAG_OFFLINE", "").lower() in {"1", "true", "yes"}:
        raise RuntimeError("RAG_OFFLINE=1，跳过加载 Reranker 权重")
    if _reranker is None:
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        from sentence_transformers import CrossEncoder

        settings = get_settings()
        device = settings.reranker_device
        model_name = settings.resolved_reranker_model
        logger.info("loading_reranker", model=model_name, device=device)
        try:
            _reranker = CrossEncoder(model_name, device=device)
        except Exception:
            logger.warning("reranker_cuda_fallback_cpu")
            _reranker = CrossEncoder(model_name, device="cpu")
    return _reranker


def rerank(query: str, texts: list[str], top_k: int) -> list[tuple[int, float]]:
    """返回 (原索引, 分数) 按分数降序。失败时按原序截断。"""
    if not texts:
        return []
    try:
        model = get_reranker()
        pairs = [[query, t] for t in texts]
        scores = model.predict(pairs)
        ranked = sorted(enumerate(scores), key=lambda x: float(x[1]), reverse=True)
        return [(i, float(s)) for i, s in ranked[:top_k]]
    except Exception as exc:
        logger.warning("rerank_fallback", error=str(exc))
        return [(i, 0.0) for i in range(min(top_k, len(texts)))]
