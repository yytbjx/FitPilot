"""知识入库：解析 → 切分 →（按文档清理）→ Qdrant + BM25。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Iterable
from uuid import NAMESPACE_URL, uuid5

from qdrant_client.http import models as qm

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import INGEST_CHUNKS
from app.rag import DocumentChunk
from app.rag.bm25 import BM25Index, get_bm25_index, persist_bm25
from app.rag.chunking import chunks_from_file, split_text
from app.rag.embeddings import embed_texts, embedding_dim
from app.rag.parsing import describe_formats, iter_source_files
from app.services.qdrant_client import get_qdrant_service

logger = get_logger(__name__)


def _point_id(chunk: DocumentChunk) -> str:
    return str(uuid5(NAMESPACE_URL, f"{chunk.document_id}:{chunk.version_id}:{chunk.chunk_id}"))


def _purge_document(svc, document_id: str, bm25_payloads: dict[str, dict]) -> int:
    """删除某文档旧向量，并从 BM25 payload 中剔除同 document_id。"""
    removed = 0
    try:
        svc.delete_by_payload("document_id", document_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("qdrant_purge_failed", document_id=document_id, error=str(exc))
    drop_ids = [
        cid
        for cid, p in bm25_payloads.items()
        if str(p.get("document_id") or "") == document_id
    ]
    for cid in drop_ids:
        bm25_payloads.pop(cid, None)
        removed += 1
    return removed


def delete_document(document_id: str) -> dict:
    """删除某文档的全部索引数据：Qdrant 向量 + BM25 条目，并持久化 bm25_index.json。

    与 ingest 的幂等重入库共用 _purge_document 清理逻辑，保证删除/重入库口径一致。
    """
    svc = get_qdrant_service()
    qdrant_ok = True
    qdrant_error: str | None = None
    try:
        svc.delete_by_payload("document_id", document_id)
    except Exception as exc:  # noqa: BLE001
        qdrant_ok = False
        qdrant_error = str(exc)
        logger.warning("qdrant_purge_failed", document_id=document_id, error=str(exc))
    bm25 = get_bm25_index()
    merged: dict[str, dict] = dict(bm25.payloads)
    drop_ids = [
        cid
        for cid, p in merged.items()
        if str(p.get("document_id") or "") == document_id
    ]
    for cid in drop_ids:
        merged.pop(cid, None)
    new_index = BM25Index()
    new_index.build(
        (cid, payload.get("text", ""), payload) for cid, payload in merged.items()
    )
    persist_bm25(new_index)
    logger.info(
        "knowledge_document_deleted",
        document_id=document_id,
        bm25_removed=len(drop_ids),
    )
    return {
        "document_id": document_id,
        "bm25_removed": len(drop_ids),
        "bm25_remaining": len(merged),
        "qdrant_purged": qdrant_ok,
        "qdrant_error": qdrant_error,
    }


async def ingest_paths(
    paths: Iterable[Path], *, version_id: str = "v1", batch_size: int = 32
) -> dict:
    settings = get_settings()
    svc = get_qdrant_service()
    svc.ensure_collection(vector_size=embedding_dim())

    all_chunks: list[DocumentChunk] = []
    skipped: list[str] = []
    format_counts: dict[str, int] = {}
    for path in paths:
        try:
            file_chunks = chunks_from_file(path, version_id=version_id)
            all_chunks.extend(file_chunks)
            fmt = "unknown"
            if file_chunks and isinstance(file_chunks[0].metadata, dict):
                fmt = str(file_chunks[0].metadata.get("parse_format") or path.suffix.lower())
            format_counts[fmt] = format_counts.get(fmt, 0) + 1
            logger.info(
                "ingest_file_ok",
                path=str(path),
                format=fmt,
                chunks=len(file_chunks),
            )
        except Exception as exc:
            skipped.append(f"{path}:{exc}")
            logger.warning("ingest_skip_file", path=str(path), error=str(exc))

    if not all_chunks:
        return {
            "ingested_chunks": 0,
            "skipped": skipped,
            "documents": 0,
            "formats": format_counts,
            "supported_formats": describe_formats(),
            "purged_docs": 0,
        }

    # 幂等：先按 document_id 清掉旧 chunk，避免文件改短后残留
    bm25 = get_bm25_index()
    merged: dict[str, dict] = dict(bm25.payloads)
    docs = sorted({c.document_id for c in all_chunks})
    purged = 0
    for doc_id in docs:
        purged += _purge_document(svc, doc_id, merged)

    for i in range(0, len(all_chunks), batch_size):
        batch = all_chunks[i : i + batch_size]
        # model.encode 为同步阻塞调用，放线程池避免阻塞事件循环
        vectors = await asyncio.to_thread(embed_texts, [c.text for c in batch])
        points = [
            qm.PointStruct(
                id=_point_id(c),
                vector=vectors[j],
                payload=c.to_payload(),
            )
            for j, c in enumerate(batch)
        ]
        svc.client.upsert(collection_name=settings.qdrant_collection, points=points)

    for c in all_chunks:
        merged[c.chunk_id] = c.to_payload()
        fmt = str((c.metadata or {}).get("parse_format") or "unknown")
        INGEST_CHUNKS.labels(format=fmt).inc()

    new_index = BM25Index()
    new_index.build(
        (cid, payload.get("text", ""), payload) for cid, payload in merged.items()
    )
    persist_bm25(new_index)

    return {
        "ingested_chunks": len(all_chunks),
        "documents": len(docs),
        "skipped": skipped,
        "formats": format_counts,
        "purged_docs": len(docs),
        "bm25_removed_approx": purged,
        "collection": settings.qdrant_collection,
    }


async def ingest_directory(root: Path, *, version_id: str = "v1") -> dict:
    files = iter_source_files(root)
    return await ingest_paths(files, version_id=version_id)


async def ingest_text_document(
    *,
    document_id: str,
    title: str,
    text: str,
    version_id: str = "v1",
) -> dict:
    chunks = split_text(
        text,
        document_id=document_id,
        version_id=version_id,
        title=title,
        source_path=f"inline:{document_id}",
    )
    settings = get_settings()
    svc = get_qdrant_service()
    svc.ensure_collection(vector_size=embedding_dim())
    if not chunks:
        return {"ingested_chunks": 0, "documents": 0}
    bm25 = get_bm25_index()
    merged = dict(bm25.payloads)
    _purge_document(svc, document_id, merged)
    vectors = await asyncio.to_thread(embed_texts, [c.text for c in chunks])
    points = [
        qm.PointStruct(id=_point_id(c), vector=vectors[i], payload=c.to_payload())
        for i, c in enumerate(chunks)
    ]
    svc.client.upsert(collection_name=settings.qdrant_collection, points=points)
    for c in chunks:
        merged[c.chunk_id] = c.to_payload()
    new_index = BM25Index()
    new_index.build((cid, p.get("text", ""), p) for cid, p in merged.items())
    persist_bm25(new_index)
    return {"ingested_chunks": len(chunks), "documents": 1, "document_id": document_id}
