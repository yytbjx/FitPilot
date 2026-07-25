"""Reranker 懒加载（加载失败即硬失败；运行期失败降级并留痕）。"""

from __future__ import annotations

import os
import threading
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import RERANK_FALLBACK

logger = get_logger(__name__)
_reranker = None
_reranker_lock = threading.Lock()
_load_error: str | None = None


class RerankerUnavailableError(RuntimeError):
    """Reranker 模型不可用（加载失败或被 RAG_OFFLINE 禁用），不再静默返回 0 分。"""


def _offline_mode() -> bool:
    return os.environ.get("RAG_OFFLINE", "").lower() in {"1", "true", "yes"}


def get_reranker():
    """加载 CrossEncoder；失败即抛 RerankerUnavailableError（fail-fast）。"""
    global _reranker, _load_error
    if _offline_mode():
        _load_error = "RAG_OFFLINE=1，Reranker 权重加载被禁用"
        raise RerankerUnavailableError(_load_error)
    if _reranker is not None:
        return _reranker
    with _reranker_lock:
        if _reranker is None:
            os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
            settings = get_settings()
            device = settings.reranker_device
            model_name = settings.resolved_reranker_model
            logger.info("loading_reranker", model=model_name, device=device)
            try:
                from sentence_transformers import CrossEncoder

                try:
                    _reranker = CrossEncoder(model_name, device=device)
                except Exception:
                    logger.warning("reranker_cuda_fallback_cpu")
                    _reranker = CrossEncoder(model_name, device="cpu")
                _load_error = None
            except Exception as exc:
                _load_error = str(exc)
                logger.error("reranker_model_load_failed", model=model_name, error=str(exc))
                raise RerankerUnavailableError(
                    f"Reranker 模型加载失败（{model_name}）：{exc}"
                ) from exc
    return _reranker


def reranker_status() -> dict[str, Any]:
    """健康检查三态：loaded / failed / not_loaded（不触发加载）。"""
    model_name = get_settings().resolved_reranker_model
    if _reranker is not None:
        return {"ok": True, "status": "loaded", "model": model_name}
    if _load_error:
        return {"ok": False, "status": "failed", "model": model_name, "error": _load_error}
    return {"ok": True, "status": "not_loaded", "model": model_name}


def rerank(query: str, texts: list[str], top_k: int) -> list[tuple[int, float]]:
    """返回 (原索引, 分数) 按分数降序。

    - 模型加载失败：fail-fast，抛 RerankerUnavailableError（避免 0 分导致全站拒答）；
    - 运行期 predict 失败：按原序截断降级，并记录 logger.error + Prometheus 指标。
    """
    if not texts:
        return []
    model = get_reranker()
    try:
        pairs = [[query, t] for t in texts]
        scores = model.predict(pairs)
        ranked = sorted(enumerate(scores), key=lambda x: float(x[1]), reverse=True)
        return [(i, float(s)) for i, s in ranked[:top_k]]
    except Exception as exc:  # noqa: BLE001 — 运行期失败可降级，但必须留痕
        RERANK_FALLBACK.inc()
        logger.error("rerank_runtime_fallback", error=str(exc))
        return [(i, 0.0) for i in range(min(top_k, len(texts)))]
