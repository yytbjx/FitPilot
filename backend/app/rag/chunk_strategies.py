"""文档类型感知分块策略（增强方案 5.2）。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from app.rag import DocumentChunk
from app.rag.chunking import split_text, split_text_parent_child, _chunk_id, _window

DocType = Literal["guide", "faq", "safety", "table", "action", "generic"]
ChunkStrategy = Literal["auto", "fixed", "heading", "parent_child", "faq_qa", "clause", "table_row"]


def detect_doc_type(
    *,
    path: str | Path = "",
    title: str = "",
    text: str = "",
    parse_format: str = "",
) -> DocType:
    p = str(path).replace("\\", "/").lower()
    t = (title or "").lower()
    head = (text or "")[:800]
    fmt = (parse_format or Path(p).suffix.lstrip(".")).lower()

    if "safety" in p or "边界" in (title or "") or re.search(r"(禁止|不得|风险|就医|医疗免责)", head):
        return "safety"
    if fmt in {"csv", "xlsx", "xls", "tsv", "json"} or "/fdc/" in p or "表格" in (title or ""):
        return "table"
    if "faq" in p or "faq" in t or re.search(r"(^|\n)\s*(Q[:：]|问[:：]|A[:：]|答[:：])", text or "", re.I):
        return "faq"
    if re.search(r"(深蹲|硬拉|卧推|动作说明|动作要领)", title or "") and len(text or "") < 2500:
        return "action"
    # 指南/准则类中文网页或整理稿：按 guide→parent_child，并配合中文章节规范化
    if (
        "guidelines" in p
        or "public_web" in p
        or "膳食指南" in (title or "")
        or "身体活动" in (title or "")
        or re.search(r"准则[一二三四五六七八]", head)
    ):
        return "guide"
    if fmt in {"md", "markdown", "docx", "pdf", "html", "htm"} or "curated" in p:
        return "guide"
    return "generic"


def strategy_for_doc_type(doc_type: DocType) -> ChunkStrategy:
    return {
        "guide": "parent_child",
        "faq": "faq_qa",
        "safety": "clause",
        "table": "table_row",
        "action": "heading",
        "generic": "heading",
    }.get(doc_type, "heading")


def split_with_strategy(
    text: str,
    *,
    document_id: str,
    version_id: str,
    title: str,
    source_path: str = "",
    strategy: ChunkStrategy = "auto",
    doc_type: DocType | None = None,
    parse_format: str = "",
    max_chars: int = 900,
    overlap: int = 120,
) -> list[DocumentChunk]:
    resolved_type = doc_type or detect_doc_type(
        path=source_path, title=title, text=text, parse_format=parse_format
    )
    resolved = strategy if strategy != "auto" else strategy_for_doc_type(resolved_type)

    if resolved == "fixed":
        chunks = _split_fixed(
            text,
            document_id=document_id,
            version_id=version_id,
            title=title,
            source_path=source_path,
            max_chars=max_chars,
            overlap=overlap,
        )
    elif resolved == "heading":
        chunks = split_text(
            text,
            document_id=document_id,
            version_id=version_id,
            title=title,
            source_path=source_path,
            max_chars=max_chars,
            overlap=overlap,
        )
    elif resolved == "parent_child":
        chunks = split_text_parent_child(
            text,
            document_id=document_id,
            version_id=version_id,
            title=title,
            source_path=source_path,
        )
    elif resolved == "faq_qa":
        chunks = _split_faq(
            text,
            document_id=document_id,
            version_id=version_id,
            title=title,
            source_path=source_path,
            max_chars=max_chars,
        )
    elif resolved == "clause":
        chunks = _split_clause(
            text,
            document_id=document_id,
            version_id=version_id,
            title=title,
            source_path=source_path,
            max_chars=min(500, max_chars),
            overlap=min(80, overlap),
        )
    elif resolved == "table_row":
        chunks = _split_table_rows(
            text,
            document_id=document_id,
            version_id=version_id,
            title=title,
            source_path=source_path,
        )
    else:
        chunks = split_text(
            text,
            document_id=document_id,
            version_id=version_id,
            title=title,
            source_path=source_path,
            max_chars=max_chars,
            overlap=overlap,
        )

    for c in chunks:
        c.metadata = {
            **(c.metadata or {}),
            "doc_type": resolved_type,
            "chunk_strategy": resolved,
            "chunk_type": c.metadata.get("chunk_type") or resolved,
        }
    return chunks


def compare_chunk_strategies(
    text: str,
    *,
    document_id: str = "cmp",
    version_id: str = "v1",
    title: str = "compare",
    source_path: str = "",
    strategies: list[ChunkStrategy] | None = None,
) -> dict[str, Any]:
    """离线对比多种分块策略的结构指标（不依赖向量库）。"""
    strategies = strategies or ["fixed", "heading", "parent_child", "faq_qa", "clause"]
    detected = detect_doc_type(path=source_path, title=title, text=text)
    results: dict[str, Any] = {"detected_doc_type": detected, "strategies": {}}
    for name in strategies:
        chunks = split_with_strategy(
            text,
            document_id=document_id,
            version_id=version_id,
            title=title,
            source_path=source_path,
            strategy=name,
            doc_type=detected,
        )
        lengths = [len(c.text) for c in chunks]
        complete = sum(1 for c in chunks if re.search(r"[。！？\.!\?：:]$", c.text.strip()))
        results["strategies"][name] = {
            "chunk_count": len(chunks),
            "avg_chars": round(sum(lengths) / len(lengths), 1) if lengths else 0,
            "max_chars": max(lengths) if lengths else 0,
            "min_chars": min(lengths) if lengths else 0,
            "complete_rate": round(complete / len(chunks), 3) if chunks else 0.0,
            "recommended": name == strategy_for_doc_type(detected),
        }
    results["recommended_strategy"] = strategy_for_doc_type(detected)
    return results


def _split_fixed(
    text: str,
    *,
    document_id: str,
    version_id: str,
    title: str,
    source_path: str,
    max_chars: int,
    overlap: int,
) -> list[DocumentChunk]:
    pieces = _window(text.strip(), max_chars=max_chars, overlap=overlap)
    chunks: list[DocumentChunk] = []
    for idx, piece in enumerate(pieces):
        cid = _chunk_id(document_id, version_id, idx, piece)
        chunks.append(
            DocumentChunk(
                document_id=document_id,
                version_id=version_id,
                chunk_id=cid,
                text=piece,
                title=title,
                section_path="",
                source_path=source_path,
                metadata={"chunk_index": idx, "chunk_type": "fixed"},
            )
        )
    return chunks


def _split_faq(
    text: str,
    *,
    document_id: str,
    version_id: str,
    title: str,
    source_path: str,
    max_chars: int,
) -> list[DocumentChunk]:
    """尽量一问一答一块；否则退回标题切分。"""
    blocks = re.split(r"(?=\n#{1,3}\s+|\n\s*(?:Q|问)[:：])", text.strip())
    blocks = [b.strip() for b in blocks if b and b.strip()]
    if len(blocks) <= 1:
        # 尝试按空行双换行切 FAQ
        blocks = [b.strip() for b in re.split(r"\n{2,}", text.strip()) if b.strip()]
    if len(blocks) <= 1:
        return split_text(
            text,
            document_id=document_id,
            version_id=version_id,
            title=title,
            source_path=source_path,
            max_chars=max_chars,
        )

    chunks: list[DocumentChunk] = []
    idx = 0
    for block in blocks:
        pieces = [block] if len(block) <= max_chars else _window(block, max_chars=max_chars, overlap=60)
        heading = ""
        m = re.match(r"^#{1,3}\s+(.+)$", block, re.M)
        if m:
            heading = m.group(1).strip()
        for piece in pieces:
            cid = _chunk_id(document_id, version_id, idx, piece)
            chunks.append(
                DocumentChunk(
                    document_id=document_id,
                    version_id=version_id,
                    chunk_id=cid,
                    text=piece,
                    title=title,
                    section_path=heading,
                    source_path=source_path,
                    metadata={"chunk_index": idx, "chunk_type": "faq"},
                )
            )
            idx += 1
    return chunks


def _split_clause(
    text: str,
    *,
    document_id: str,
    version_id: str,
    title: str,
    source_path: str,
    max_chars: int,
    overlap: int,
) -> list[DocumentChunk]:
    """条款级：按标题/编号条款切，保留章节路径。"""
    parts = re.split(r"(?=\n#{1,6}\s+|\n\s*\d+[\.、]\s+|\n\s*[（(]\d+[）)]\s*)", text.strip())
    parts = [p.strip() for p in parts if p and p.strip()]
    if not parts:
        parts = [text.strip()]
    chunks: list[DocumentChunk] = []
    idx = 0
    for part in parts:
        heading = ""
        hm = re.match(r"^(?:#{1,6}\s+(.+)|(\d+[\.、].{0,40}))", part)
        if hm:
            heading = (hm.group(1) or hm.group(2) or "").strip()
        pieces = [part] if len(part) <= max_chars else _window(part, max_chars=max_chars, overlap=overlap)
        for piece in pieces:
            cid = _chunk_id(document_id, version_id, idx, piece)
            chunks.append(
                DocumentChunk(
                    document_id=document_id,
                    version_id=version_id,
                    chunk_id=cid,
                    text=piece,
                    title=title,
                    section_path=heading,
                    source_path=source_path,
                    metadata={"chunk_index": idx, "chunk_type": "clause"},
                )
            )
            idx += 1
    return chunks


def _split_table_rows(
    text: str,
    *,
    document_id: str,
    version_id: str,
    title: str,
    source_path: str,
) -> list[DocumentChunk]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    # 保留表头 + 每行一块（或表头摘要 + 批量行）
    header = lines[0]
    body = lines[1:] if len(lines) > 1 else []
    chunks: list[DocumentChunk] = []
    if not body:
        cid = _chunk_id(document_id, version_id, 0, header)
        return [
            DocumentChunk(
                document_id=document_id,
                version_id=version_id,
                chunk_id=cid,
                text=header,
                title=title,
                section_path="table",
                source_path=source_path,
                metadata={"chunk_index": 0, "chunk_type": "table"},
            )
        ]
    # 总表摘要
    summary = f"{title}\n表头：{header}\n共 {len(body)} 行"
    cid0 = _chunk_id(document_id, version_id, 0, summary)
    chunks.append(
        DocumentChunk(
            document_id=document_id,
            version_id=version_id,
            chunk_id=cid0,
            text=summary,
            title=title,
            section_path="table/summary",
            source_path=source_path,
            metadata={"chunk_index": 0, "chunk_type": "table_summary"},
        )
    )
    for i, row in enumerate(body, start=1):
        piece = f"{header}\n{row}"
        cid = _chunk_id(document_id, version_id, i, piece)
        chunks.append(
            DocumentChunk(
                document_id=document_id,
                version_id=version_id,
                chunk_id=cid,
                text=piece,
                title=title,
                section_path=f"table/row_{i}",
                source_path=source_path,
                metadata={"chunk_index": i, "chunk_type": "table_row"},
            )
        )
    return chunks
