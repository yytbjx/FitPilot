"""Qdrant 向量库客户端：连接本机 Docker 中的 Qdrant。"""

from __future__ import annotations

import os
from typing import Any

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

    def document_id_set(self, *, page_limit: int = 256) -> set[str]:
        """滚动扫描集合 payload，返回 document_id 集合（用于 BM25/Qdrant 一致性校验）。

        只取 payload 不取向量；集合不存在时返回空集。
        """
        existing = {c.name for c in self.client.get_collections().collections}
        if self.collection not in existing:
            return set()
        docs: set[str] = set()
        offset = None
        while True:
            points, offset = self.client.scroll(
                collection_name=self.collection,
                limit=page_limit,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for p in points:
                payload = p.payload or {}
                doc = str(payload.get("document_id") or "")
                if doc:
                    docs.add(doc)
            if offset is None:
                break
        return docs

    def create_snapshot(self) -> dict[str, Any]:
        """创建当前知识集合快照（存储于 Qdrant 服务端）。"""
        snap = self.client.create_snapshot(collection_name=self.collection)
        name = getattr(snap, "name", None) or str(snap)
        logger.info("qdrant_snapshot_created", collection=self.collection, name=name)
        return {"ok": True, "collection": self.collection, "name": name, "snapshot": str(snap)}

    def list_snapshots(self) -> list[dict[str, Any]]:
        snaps = self.client.list_snapshots(collection_name=self.collection) or []
        out: list[dict[str, Any]] = []
        for s in snaps:
            out.append(
                {
                    "name": getattr(s, "name", None) or str(s),
                    "creation_time": str(getattr(s, "creation_time", "") or ""),
                    "size": getattr(s, "size", None),
                }
            )
        return out

    def recover_snapshot(self, snapshot_name: str, *, wait: bool = True) -> dict[str, Any]:
        """从集合快照恢复（覆盖当前集合数据）。"""
        # qdrant-client: recover_snapshot(collection_name, location)
        location = snapshot_name
        if not location.startswith("file://") and "/" not in location and "\\" not in location:
            # 相对名：使用 Qdrant 本地快照路径约定
            location = f"file:///qdrant/snapshots/{self.collection}/{snapshot_name}"
        try:
            self.client.recover_snapshot(
                collection_name=self.collection,
                location=location,
                wait=wait,
            )
        except Exception as exc:  # noqa: BLE001
            # 回退：部分版本 API 为 snapshot_name 参数
            try:
                self.client.recover_snapshot(
                    collection_name=self.collection,
                    location=snapshot_name,
                    wait=wait,
                )
            except Exception as exc2:  # noqa: BLE001
                logger.warning("qdrant_recover_failed", error=str(exc), error2=str(exc2))
                return {"ok": False, "error": str(exc2), "tried_location": location}
        logger.info("qdrant_snapshot_recovered", collection=self.collection, location=location)
        return {"ok": True, "collection": self.collection, "location": location}


_svc: QdrantService | None = None


def get_qdrant_service() -> QdrantService:
    global _svc
    if _svc is None:
        _svc = QdrantService()
    return _svc
