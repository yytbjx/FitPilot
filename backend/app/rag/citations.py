"""Citation 映射：证据 → 可定位引用。"""

from __future__ import annotations

import re
from typing import Any

from app.rag import RetrievedChunk
from app.rag.knowledge_lifecycle import get_active_index_version


def map_citations(
    chunks: list[RetrievedChunk],
    *,
    answer_text: str | None = None,
    index_version: str | None = None,
) -> list[dict[str, Any]]:
    """将检索块映射为前端/评测可用的引用结构。

    若提供 answer_text，会标记哪些编号被回答引用（Citation Coverage）。
    """
    active = index_version
    if active is None:
        meta = get_active_index_version() or {}
        active = str(meta.get("index_version") or "") or None

    cited_indices: set[int] = set()
    if answer_text:
        for m in re.finditer(r"\[(\d+)\]", answer_text):
            cited_indices.add(int(m.group(1)))

    out: list[dict[str, Any]] = []
    for i, c in enumerate(chunks, start=1):
        md = c.metadata or {}
        item = {
            "index": i,
            "citation": c.citation or f"{c.document_id}#{c.chunk_id}",
            "title": c.title,
            "section_path": c.section_path,
            "heading_path": _heading_path(c.section_path),
            "document_id": c.document_id,
            "version_id": c.version_id,
            "chunk_id": c.chunk_id,
            "source_path": c.source_path or md.get("source_path"),
            "score": c.score,
            "authority_level": md.get("authority_level"),
            "doc_type": md.get("doc_type"),
            "chunk_strategy": md.get("chunk_strategy") or md.get("chunk_type"),
            "page_number": md.get("page_number") or md.get("page"),
            "index_version": active,
            "snippet": (c.text or "")[:240],
            "cited_in_answer": i in cited_indices if answer_text is not None else None,
        }
        out.append(item)

    return out


def citation_coverage(citations: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(citations)
    cited = sum(1 for c in citations if c.get("cited_in_answer") is True)
    return {
        "total_evidence": total,
        "cited_count": cited,
        "coverage": round(cited / total, 3) if total else 0.0,
    }


def _heading_path(section_path: str | None) -> list[str]:
    if not section_path:
        return []
    parts = re.split(r"[>/\\|]+", section_path)
    return [p.strip() for p in parts if p and p.strip()]
