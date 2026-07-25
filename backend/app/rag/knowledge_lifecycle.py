"""知识源增量入库与索引版本。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import get_engine
from app.models.knowledge_source import KnowledgeSource
from app.rag.embeddings import embedding_dim
from app.rag.ingest import delete_document, ingest_paths
from app.rag.parsing import iter_source_files

logger = get_logger(__name__)

CHUNKER_VERSION = "heading-900-120"
PARSER_VERSION = "registry-v1"
INDEX_META_NAME = "index_versions.jsonl"


def current_index_signature() -> dict[str, Any]:
    """当前索引配置指纹：embedding 模型 + 维度 + 分块策略 + CHUNKER_VERSION。

    任一组件变化都会改变 index_signature，用于发现「索引与配置不匹配、需要 re-ingest」。
    维度获取失败（如离线模式）时记为 None，不阻断流程。
    """
    settings = get_settings()
    try:
        dim: int | None = embedding_dim()
    except Exception:  # noqa: BLE001 — 模型未加载/离线时指纹退化为 unknown
        dim = None
    parts = {
        "embedding_model": settings.resolved_embedding_model,
        "embedding_dim": dim,
        "chunk_strategy": str(settings.rag_chunk_strategy),
        "chunker_version": CHUNKER_VERSION,
        "parser_version": PARSER_VERSION,
    }
    raw = "|".join(str(parts[k]) for k in sorted(parts))
    return {**parts, "index_signature": hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]}


def check_active_version_compatible() -> dict[str, Any]:
    """对比 active 版本指纹与当前配置；不匹配时打 warning（提示需 re-ingest，不自动重建）。"""
    current = current_index_signature()
    active = get_active_index_version()
    active_sig = str((active or {}).get("index_signature") or "")
    if active and not active_sig:
        # 老版本记录没有指纹字段：按 embedding_model + chunker_version 粗判
        legacy_match = (
            str(active.get("embedding_model") or "") == current["embedding_model"]
            and str(active.get("chunker_version") or "") == current["chunker_version"]
        )
        if not legacy_match:
            logger.warning(
                "index_version_config_mismatch",
                active=active.get("index_version"),
                reason="legacy 记录 embedding/chunker 与当前配置不一致，建议 re-ingest",
            )
        return {"compatible": legacy_match, "legacy_check": True, "current": current}
    match = bool(active_sig) and active_sig == current["index_signature"]
    if active and not match:
        logger.warning(
            "index_version_config_mismatch",
            active=active.get("index_version"),
            active_signature=active_sig,
            current_signature=current["index_signature"],
            reason="索引版本指纹与当前配置不匹配，Embedding/分块配置可能已变更，建议 re-ingest",
        )
    return {"compatible": match, "current": current, "active_signature": active_sig or None}


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _source_id_for(path: Path, root: Path) -> str:
    rel = str(path.relative_to(root)).replace("\\", "/")
    return hashlib.sha1(rel.encode("utf-8")).hexdigest()[:16]


def index_meta_path() -> Path:
    root = get_settings().project_root
    return root / "knowledge_base" / INDEX_META_NAME


def append_index_version(meta: dict[str, Any]) -> Path:
    path = index_meta_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False) + "\n")
    return path


def active_index_pointer_path() -> Path:
    root = get_settings().project_root
    return root / "knowledge_base" / "active_index_version.json"


def set_active_index_version(meta: dict[str, Any]) -> Path:
    path = active_index_pointer_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def get_active_index_version() -> dict[str, Any] | None:
    path = active_index_pointer_path()
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return latest_index_version()


def list_index_versions() -> list[dict[str, Any]]:
    path = index_meta_path()
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def find_index_version(version_id: str) -> dict[str, Any] | None:
    for item in list_index_versions():
        if str(item.get("index_version")) == version_id:
            return item
    return None


async def rollback_index_version(
    version_id: str,
    *,
    raw_dir: Path | None = None,
    reset_collection: bool = True,
) -> dict[str, Any]:
    """回滚到历史 index_version：重建集合并按该版本文件集重新入库。

    无 Qdrant 快照时，回滚通过「按版本清单重入库」实现，并写入新的 rollback 记录。
    """
    target = find_index_version(version_id)
    if not target:
        return {"ok": False, "error": "VERSION_NOT_FOUND", "version": version_id}

    settings = get_settings()
    raw = raw_dir or (settings.project_root / "knowledge_base" / "raw")
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)

    if reset_collection:
        from app.services.qdrant_client import get_qdrant_service

        # 回滚前尽量打快照，便于再次恢复
        try:
            snap = get_qdrant_service().create_snapshot()
            logger.info("pre_rollback_snapshot", snapshot=snap)
        except Exception as exc:  # noqa: BLE001
            logger.warning("pre_rollback_snapshot_failed", error=str(exc))
        get_qdrant_service().reset_collection()

    changed = target.get("changed_files") or []
    mode = target.get("mode") or "reset"
    if mode == "reset" or not changed:
        paths = list(iter_source_files(raw))
    else:
        paths = [Path(p) for p in changed if Path(p).exists()]
        if not paths:
            # 已知局限（不重写）：目标版本的文件清单若已全部从 raw/ 删除，
            # 此处会静默 fallback 为「全量 raw 重入库」，回滚结果可能偏离目标版本
            # 的真实文件集。无 Qdrant 快照时无法还原已删文件，建议回滚前用
            # knowledge-snapshot create 打快照，或对已删文件的版本禁用回滚。
            paths = list(iter_source_files(raw))

    result = await ingest_paths(paths)
    await _upsert_sources(factory, raw, paths, status="ready")
    ver = {
        "index_version": f"idx_{uuid4().hex[:10]}",
        **current_index_signature(),
        "source_count": len(paths),
        "chunk_count": result.get("ingested_chunks"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready",
        "mode": "rollback",
        "rollback_of": version_id,
        "changed_files": [str(p) for p in paths],
    }
    append_index_version(ver)
    set_active_index_version(ver)
    result["ok"] = True
    result["index_version"] = ver
    result["rolled_back_to"] = target
    return result


def latest_index_version() -> dict[str, Any] | None:
    path = index_meta_path()
    if not path.exists():
        return None
    last = None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            last = json.loads(line)
    return last


async def diff_knowledge_dir(raw_dir: Path) -> dict[str, Any]:
    """比较磁盘文件与 knowledge_sources，返回新增/变更/未变/已删除。"""
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    files = list(iter_source_files(raw_dir))
    async with factory() as db:
        rows = list((await db.scalars(select(KnowledgeSource))).all())
        by_id = {r.source_id: r for r in rows}
        current_sids: set[str] = set()
        added: list[str] = []
        changed: list[str] = []
        unchanged: list[str] = []
        for path in files:
            sid = _source_id_for(path, raw_dir)
            current_sids.add(sid)
            digest = _file_hash(path)
            row = by_id.get(sid)
            if row is None:
                added.append(str(path))
            elif row.content_hash != digest:
                changed.append(str(path))
            else:
                unchanged.append(str(path))
        # deleted：manifest 中有记录、但 raw/ 下文件已消失
        deleted: list[dict[str, Any]] = []
        for row in rows:
            if row.source_id in current_sids:
                continue
            deleted.append(
                {
                    "source_id": row.source_id,
                    "title": row.title,
                    "original_path": row.original_path,
                    # document_id 与入库时一致：文件 stem（见 chunking.chunks_from_file）
                    "document_id": (
                        Path(row.original_path).stem if row.original_path else row.title
                    ),
                }
            )
        return {
            "added": added,
            "changed": changed,
            "unchanged": unchanged,
            "deleted": deleted,
            "total_files": len(files),
            "tracked_sources": len(rows),
        }


async def delete_source(source_id: str) -> dict[str, Any]:
    """删除知识源：Postgres manifest 记录 + Qdrant chunks + BM25 条目（持久化 bm25_index.json）。

    document_id 按入库约定取 original_path 的 stem。
    """
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as db:
        row = await db.scalar(select(KnowledgeSource).where(KnowledgeSource.source_id == source_id))
        if row is None:
            return {"ok": False, "error": "SOURCE_NOT_FOUND", "source_id": source_id}
        document_id = Path(row.original_path).stem if row.original_path else row.title
        await db.delete(row)
        await db.commit()
    # Qdrant HTTP + BM25 文件持久化为阻塞调用，放线程池执行
    result = await asyncio.to_thread(delete_document, document_id)
    result.update({"ok": True, "source_id": source_id})
    return result


def index_consistency_report() -> dict[str, Any]:
    """BM25 / Qdrant 两侧 document_id 集合差异计数（轻量一致性校验，可观测用）。"""
    from app.rag.bm25 import get_bm25_index
    from app.services.qdrant_client import get_qdrant_service

    bm25 = get_bm25_index()
    bm25_docs = {
        str(p.get("document_id") or "") for p in bm25.payloads.values()
    } - {""}
    qdrant_docs: set[str] | None = None
    qdrant_error: str | None = None
    try:
        qdrant_docs = get_qdrant_service().document_id_set()
    except Exception as exc:  # noqa: BLE001
        qdrant_error = str(exc)
    report: dict[str, Any] = {
        "bm25_documents": len(bm25_docs),
        "bm25_chunks": len(bm25.payloads),
        "qdrant_error": qdrant_error,
    }
    if qdrant_docs is not None:
        report.update(
            {
                "qdrant_documents": len(qdrant_docs),
                "only_in_bm25": sorted(bm25_docs - qdrant_docs),
                "only_in_qdrant": sorted(qdrant_docs - bm25_docs),
                "diff_count": len(bm25_docs ^ qdrant_docs),
            }
        )
    return report


async def ingest_incremental(
    raw_dir: Path,
    *,
    reset: bool = False,
    prune_deleted: bool = True,
) -> dict[str, Any]:
    """仅入库新增/变更文件；并写入 knowledge_sources + index_version。

    prune_deleted=True 时，对 diff 出的 deleted（raw/ 已消失的文件）执行清理传播：
    删除 manifest 记录 + Qdrant chunks + BM25 条目（与 delete_source 同一清理路径）。
    ingest 前若 active 索引版本指纹与当前配置不匹配，打 warning 提示需 re-ingest。
    """
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)

    compat = check_active_version_compatible()
    if not compat.get("compatible"):
        logger.warning(
            "ingest_with_mismatched_index_version",
            hint="active 索引版本与当前 Embedding/分块配置不一致；本次入库后建议全量 re-ingest",
        )

    if reset:
        # 全量：仍走 ingest_paths，但同步刷新 manifest
        paths = list(iter_source_files(raw_dir))
        result = await ingest_paths(paths)
        await _upsert_sources(factory, raw_dir, paths, status="ready")
        ver = {
            "index_version": f"idx_{uuid4().hex[:10]}",
            **current_index_signature(),
            "source_count": len(paths),
            "chunk_count": result.get("ingested_chunks"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "ready",
            "mode": "reset",
        }
        append_index_version(ver)
        set_active_index_version(ver)
        result["index_version"] = ver
        result["version_compat"] = compat
        return result

    diff = await diff_knowledge_dir(raw_dir)
    pruned: list[dict[str, Any]] = []
    if prune_deleted:
        for item in diff.get("deleted") or []:
            try:
                pruned.append(await delete_source(str(item["source_id"])))
            except Exception as exc:  # noqa: BLE001 — 单个清理失败不阻断入库
                logger.warning(
                    "prune_deleted_failed", source_id=item.get("source_id"), error=str(exc)
                )
                pruned.append({"ok": False, "source_id": item.get("source_id"), "error": str(exc)})
        if pruned:
            # 清理后 deleted 已处理，diff 中保留快照供审计
            logger.info("pruned_deleted_sources", count=len(pruned))
    todo = [Path(p) for p in (diff["added"] + diff["changed"])]
    if not todo:
        ver = latest_index_version() or {
            "index_version": "unchanged",
            "status": "ready",
            "mode": "incremental",
        }
        return {
            "ingested_chunks": 0,
            "documents": 0,
            "skipped_unchanged": len(diff["unchanged"]),
            "diff": diff,
            "pruned_deleted": pruned,
            "index_version": ver,
            "version_compat": compat,
            "message": "无变更文件",
        }

    result = await ingest_paths(todo)
    await _upsert_sources(factory, raw_dir, todo, status="ready")
    ver = {
        "index_version": f"idx_{uuid4().hex[:10]}",
        **current_index_signature(),
        "source_count": len(todo),
        "chunk_count": result.get("ingested_chunks"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready",
        "mode": "incremental",
        "changed_files": [str(p) for p in todo],
        "pruned_deleted": [p.get("source_id") for p in pruned],
    }
    append_index_version(ver)
    set_active_index_version(ver)
    result["diff"] = diff
    result["pruned_deleted"] = pruned
    result["index_version"] = ver
    result["version_compat"] = compat
    return result


async def _upsert_sources(
    factory: async_sessionmaker[AsyncSession],
    raw_dir: Path,
    paths: list[Path],
    *,
    status: str,
) -> None:
    settings = get_settings()
    async with factory() as db:
        for path in paths:
            sid = _source_id_for(path, raw_dir)
            digest = _file_hash(path)
            row = await db.scalar(select(KnowledgeSource).where(KnowledgeSource.source_id == sid))
            title = path.stem
            if row is None:
                db.add(
                    KnowledgeSource(
                        source_id=sid,
                        title=title,
                        source_type=path.suffix.lower().lstrip(".") or "file",
                        original_path=str(path),
                        content_hash=digest,
                        document_version="v1",
                        parser_version=PARSER_VERSION,
                        chunker_version=CHUNKER_VERSION,
                        embedding_version=settings.resolved_embedding_model,
                        authority_level=2 if "curated" in str(path).replace("\\", "/") else 1,
                        language="zh",
                        ingestion_status=status,
                    )
                )
            else:
                row.title = title
                row.content_hash = digest
                row.original_path = str(path)
                row.parser_version = PARSER_VERSION
                row.chunker_version = CHUNKER_VERSION
                row.embedding_version = settings.resolved_embedding_model
                row.ingestion_status = status
        await db.commit()
