"""Qdrant 向量库客户端：连接本机 Docker 中的 Qdrant。"""

from __future__ import annotations

import os
from typing import Any

import httpx
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _bypass_local_proxy() -> None:
    """避免系统代理劫持 127.0.0.1（常见 502）。"""
    for key in ("NO_PROXY", "no_proxy"):
        cur = os.environ.get(key, "")
        parts = {p.strip() for p in cur.split(",") if p.strip()}
        parts.update({"127.0.0.1", "localhost", "::1"})
        os.environ[key] = ",".join(sorted(parts))


class QdrantService:
    """知识库向量集合的基础操作（健康检查 / 确保集合存在）。"""

    def __init__(self) -> None:
        settings = get_settings()
        self.collection = settings.qdrant_collection
        _bypass_local_proxy()
        # trust_env=False：不走系统 HTTP(S)_PROXY
        self._http = httpx.Client(timeout=30.0, trust_env=False)
        self.client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key or None,
            timeout=30,
            prefer_grpc=False,
        )
        # 覆盖 REST 底层 session 较难，二次确认连接；必要时直接用 URL
        self.vector_size = 512
        try:
            # 强制一次本地探测
            self.client.get_collections()
        except Exception as exc:  # noqa: BLE001
            logger.warning("qdrant_init_probe_failed", error=str(exc))
            # 回退：显式 host/port
            from urllib.parse import urlparse

            parsed = urlparse(settings.qdrant_url)
            self.client = QdrantClient(
                host=parsed.hostname or "127.0.0.1",
                port=parsed.port or 6333,
                api_key=settings.qdrant_api_key or None,
                timeout=30,
                prefer_grpc=False,
                https=False,
            )

    def health(self) -> dict[str, Any]:
        """探测 Qdrant 就绪状态与集合列表。"""
        collections = self.client.get_collections().collections
        names = [c.name for c in collections]
        return {
            "ok": True,
            "url": get_settings().qdrant_url,
            "collections": names,
            "default_collection": self.collection,
            "default_exists": self.collection in names,
        }

    def ensure_collection(self, vector_size: int | None = None) -> None:
        """若默认知识集合不存在则创建（Cosine + Dense）。"""
        if vector_size:
            self.vector_size = vector_size
        existing = {c.name for c in self.client.get_collections().collections}
        if self.collection in existing:
            return
        logger.info("creating_qdrant_collection", name=self.collection, size=self.vector_size)
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=qmodels.VectorParams(
                size=self.vector_size,
                distance=qmodels.Distance.COSINE,
            ),
        )

    def reset_collection(self, vector_size: int | None = None) -> None:
        """删除并重建默认知识集合（不影响 Postgres 业务库）。"""
        if vector_size:
            self.vector_size = vector_size
        existing = {c.name for c in self.client.get_collections().collections}
        if self.collection in existing:
            logger.info("deleting_qdrant_collection", name=self.collection)
            self.client.delete_collection(self.collection)
        self.ensure_collection(vector_size=self.vector_size)

    def delete_by_payload(self, field: str, value: str) -> None:
        """按 payload 字段删除点（用于幂等重入库）。"""
        flt = qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key=field,
                    match=qmodels.MatchValue(value=value),
                )
            ]
        )
        self.client.delete(
            collection_name=self.collection,
            points_selector=qmodels.FilterSelector(filter=flt),
        )
        logger.info("qdrant_delete_by_payload", field=field, value=value)

    def count_points(self) -> int | None:
        try:
            info = self.client.get_collection(self.collection)
            return int(getattr(info, "points_count", None) or 0)
        except Exception:
            return None


_svc: QdrantService | None = None


def get_qdrant_service() -> QdrantService:
    global _svc
    if _svc is None:
        _svc = QdrantService()
    return _svc
