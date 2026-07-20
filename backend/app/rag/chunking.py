"""章节感知递归切分。"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from app.rag import DocumentChunk
from app.rag.parent_child import split_parent_child

_HEADING = re.compile(r"^(#{1,6})\s+(.+)$", re.M)


def _chunk_id(document_id: str, version_id: str, idx: int, text: str) -> str:
    h = hashlib.sha1(f"{document_id}|{version_id}|{idx}|{text}".encode("utf-8")).hexdigest()[:16]
    return f"{document_id}_{idx}_{h}"


def split_text(
    text: str,
    *,
    document_id: str,
    version_id: str,
    title: str,
    source_path: str = "",
    max_chars: int = 900,
    overlap: int = 120,
) -> list[DocumentChunk]:
    """优先按 Markdown 标题切，再对超长段递归。"""
    sections: list[tuple[str, str]] = []
    matches = list(_HEADING.finditer(text))
    if not matches:
        sections.append(("", text))
    else:
        for i, m in enumerate(matches):
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            section = m.group(2).strip()
            body = text[start:end].strip()
            sections.append((section, body if body else m.group(0)))

    chunks: list[DocumentChunk] = []
    idx = 0
    for section_path, body in sections:
        if not body.strip():
            continue
        # 结构化短条目（食谱/动作式一行多字段）不硬拆
        if len(body) <= max_chars and ("\t" in body or body.count("\n") <= 8):
            pieces = [body]
        else:
            pieces = _window(body, max_chars=max_chars, overlap=overlap)
        for piece in pieces:
            cid = _chunk_id(document_id, version_id, idx, piece)
            chunks.append(
                DocumentChunk(
                    document_id=document_id,
                    version_id=version_id,
                    chunk_id=cid,
                    text=piece,
                    title=title,
                    section_path=section_path,
                    source_path=source_path,
                    metadata={"chunk_index": idx, "chunk_hash": cid},
                )
            )
            idx += 1
    return chunks


def split_text_parent_child(
    text: str,
    *,
    document_id: str,
    version_id: str,
    title: str,
    source_path: str = "",
) -> list[DocumentChunk]:
    """Parent-Child 分块：仅索引子块，父块文本写入 metadata。"""
    _, children = split_parent_child(
        text,
        document_id=document_id,
        version_id=version_id,
        title=title,
        source_path=source_path,
    )
    return children or split_text(
        text,
        document_id=document_id,
        version_id=version_id,
        title=title,
        source_path=source_path,
    )


def _window(text: str, *, max_chars: int, overlap: int) -> list[str]:
    text = text.strip()
    if len(text) <= max_chars:
        return [text]
    out: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        out.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return [x for x in out if x]


def chunks_from_file(path: Path, *, version_id: str = "v1") -> list[DocumentChunk]:
    from app.rag.parsing import parse_file_rich

    result = parse_file_rich(path)
    title, text = result.title, result.text
    doc_id = path.stem
    chunks = split_text_parent_child(
        text,
        document_id=doc_id,
        version_id=version_id,
        title=title,
        source_path=str(path),
    )
    for c in chunks:
        c.metadata = {
            **(c.metadata or {}),
            "parse_format": result.format,
            **{f"parse_{k}": v for k, v in (result.metadata or {}).items() if isinstance(v, (str, int, float, bool))},
        }
    return chunks
