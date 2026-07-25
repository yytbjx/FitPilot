"""Embedding 懒加载（失败即硬失败；并发首次加载由锁保护）。"""

from __future__ import annotations

import os
import threading
from functools import lru_cache
from typing import Any, Sequence

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
_model = None
_model_lock = threading.Lock()
_load_error: str | None = None


class EmbeddingUnavailableError(RuntimeError):
    """Embedding 模型不可用（加载失败或被 RAG_OFFLINE 禁用），不再回退哈希向量。"""


def _offline_mode() -> bool:
    return os.environ.get("RAG_OFFLINE", "").lower() in {"1", "true", "yes"}


def get_embedding_model():
    """加载 SentenceTransformer；失败即抛 EmbeddingUnavailableError（fail-fast）。"""
    global _model, _load_error
    if _offline_mode():
        _load_error = "RAG_OFFLINE=1，Embedding 权重加载被禁用"
        raise EmbeddingUnavailableError(_load_error)
    if _model is not None:
        return _model
    with _model_lock:
        if _model is None:
            os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
            settings = get_settings()
            device = settings.embedding_device
            model_name = settings.resolved_embedding_model
            logger.info("loading_embedding_model", model=model_name, device=device)
            try:
                from sentence_transformers import SentenceTransformer

                try:
                    _model = SentenceTransformer(model_name, device=device)
                except Exception:
                    logger.warning("embedding_cuda_fallback_cpu", model=model_name)
                    _model = SentenceTransformer(model_name, device="cpu")
                _load_error = None
            except Exception as exc:
                _load_error = str(exc)
                logger.error("embedding_model_load_failed", model=model_name, error=str(exc))
                raise EmbeddingUnavailableError(
                    f"Embedding 模型加载失败（{model_name}）：{exc}"
                ) from exc
    return _model


def embedding_status() -> dict[str, Any]:
    """健康检查三态：loaded / failed / not_loaded（不触发加载）。"""
    model_name = get_settings().resolved_embedding_model
    if _model is not None:
        return {"ok": True, "status": "loaded", "model": model_name}
    if _load_error:
        return {"ok": False, "status": "failed", "model": model_name, "error": _load_error}
    return {"ok": True, "status": "not_loaded", "model": model_name}


def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    """编码文本；模型不可用即抛 EmbeddingUnavailableError。"""
    model = get_embedding_model()
    vectors = model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False)
    return [v.tolist() for v in vectors]


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]


@lru_cache(maxsize=1)
def embedding_dim() -> int:
    """从已加载模型动态获取向量维度（不再硬编码 512）。

    优先使用配置项 embedding_dim_override（用于离线/测试场景）；
    否则触发模型加载并调用 get_sentence_embedding_dimension()。
    模型不可用时抛出 EmbeddingUnavailableError（与 embed_texts 口径一致，fail-fast）。
    """
    override = get_settings().embedding_dim_override
    if override:
        return int(override)
    model = get_embedding_model()
    dim = model.get_sentence_embedding_dimension()
    if not dim:
        raise EmbeddingUnavailableError("无法从 Embedding 模型获取向量维度")
    return int(dim)
