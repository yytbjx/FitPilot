"""Embedding 懒加载（支持 cuda/cpu 错峰；无权重时可哈希回退）。"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Sequence

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
_model = None


def _offline_mode() -> bool:
    return os.environ.get("RAG_OFFLINE", "").lower() in {"1", "true", "yes"}


def get_embedding_model():
    """加载 SentenceTransformer；离线模式直接失败以触发哈希回退。"""
    global _model
    if _offline_mode():
        raise RuntimeError("RAG_OFFLINE=1，跳过加载 Embedding 权重")
    if _model is None:
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        from sentence_transformers import SentenceTransformer

        settings = get_settings()
        device = settings.embedding_device
        model_name = settings.resolved_embedding_model
        logger.info("loading_embedding_model", model=model_name, device=device)
        try:
            _model = SentenceTransformer(model_name, device=device)
        except Exception:
            logger.warning("embedding_cuda_fallback_cpu", model=model_name)
            _model = SentenceTransformer(model_name, device="cpu")
    return _model


def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    """编码文本；无模型权重时回退为确定性哈希向量（便于先联调 BM25/流程）。"""
    try:
        model = get_embedding_model()
        vectors = model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False)
        return [v.tolist() for v in vectors]
    except Exception as exc:
        logger.warning("embed_fallback_hash", error=str(exc))
        return [_hash_vec(t) for t in texts]


def _hash_vec(text: str, dim: int = 512) -> list[float]:
    import hashlib
    import math

    seed = hashlib.sha256(text.encode("utf-8")).digest()
    vals: list[float] = []
    buf = seed
    while len(vals) < dim:
        buf = hashlib.sha256(buf).digest()
        for b in buf:
            vals.append((b / 255.0) * 2 - 1)
            if len(vals) >= dim:
                break
    norm = math.sqrt(sum(v * v for v in vals)) or 1.0
    return [v / norm for v in vals]


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]


@lru_cache(maxsize=1)
def embedding_dim() -> int:
    return 512
