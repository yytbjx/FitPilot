"""知识源增量入库与索引版本。"""

from __future__ import annotations

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
from app.rag.ingest import ingest_paths
from app.rag.parsing import iter_source_files

logger = get_logger(__name__)

CHUNKER_VERSION = "heading-900-120"
PARSER_VERSION = "registry-v1"
INDEX_META_NAME = "index_versions.jsonl"


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
            paths = list(iter_source_files(raw))

    result = await ingest_paths(paths)
    await _upsert_sources(factory, raw, paths, status="ready")
    ver = {
        "index_version": f"idx_{uuid4().hex[:10]}",
        "embedding_model": settings.resolved_embedding_model,
        "chunker_version": CHUNKER_VERSION,
        "parser_version": PARSER_VERSION,
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
    """比较磁盘文件与 knowledge_sources，返回新增/变更/未变。"""
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    files = list(iter_source_files(raw_dir))
    async with factory() as db:
        rows = list((await db.scalars(select(KnowledgeSource))).all())
        by_id = {r.source_id: r for r in rows}
        added: list[str] = []
        changed: list[str] = []
        unchanged: list[str] = []
        for path in files:
            sid = _source_id_for(path, raw_dir)
            digest = _file_hash(path)
            row = by_id.get(sid)
            if row is None:
                added.append(str(path))
            elif row.content_hash != digest:
                changed.append(str(path))
            else:
                unchanged.append(str(path))
        return {
            "added": added,
            "changed": changed,
            "unchanged": unchanged,
            "total_files": len(files),
            "tracked_sources": len(rows),
        }


async def ingest_incremental(
    raw_dir: Path,
    *,
    reset: bool = False,
) -> dict[str, Any]:
    """仅入库新增/变更文件；并写入 knowledge_sources + index_version。"""
    settings = get_settings()
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)

    if reset:
        # 全量：仍走 ingest_paths，但同步刷新 manifest
        paths = list(iter_source_files(raw_dir))
        result = await ingest_paths(paths)
        await _upsert_sources(factory, raw_dir, paths, status="ready")
        ver = {
            "index_version": f"idx_{uuid4().hex[:10]}",
            "embedding_model": settings.resolved_embedding_model,
            "chunker_version": CHUNKER_VERSION,
            "parser_version": PARSER_VERSION,
            "source_count": len(paths),
            "chunk_count": result.get("ingested_chunks"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "ready",
            "mode": "reset",
        }
        append_index_version(ver)
        set_active_index_version(ver)
        result["index_version"] = ver
        return result

    diff = await diff_knowledge_dir(raw_dir)
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
            "index_version": ver,
            "message": "无变更文件",
        }

    result = await ingest_paths(todo)
    await _upsert_sources(factory, raw_dir, todo, status="ready")
    ver = {
        "index_version": f"idx_{uuid4().hex[:10]}",
        "embedding_model": settings.resolved_embedding_model,
        "chunker_version": CHUNKER_VERSION,
        "parser_version": PARSER_VERSION,
        "source_count": len(todo),
        "chunk_count": result.get("ingested_chunks"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready",
        "mode": "incremental",
        "changed_files": [str(p) for p in todo],
    }
    append_index_version(ver)
    set_active_index_version(ver)
    result["diff"] = diff
    result["index_version"] = ver
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
