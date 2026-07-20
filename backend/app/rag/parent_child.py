"""Parent-Child 分块：父块保留上下文，子块用于检索。"""

from __future__ import annotations

import hashlib
from typing import Any

from app.rag import DocumentChunk


def _pid(document_id: str, version_id: str, parent_idx: int, text: str) -> str:
    h = hashlib.sha1(f"parent|{document_id}|{version_id}|{parent_idx}|{text[:200]}".encode()).hexdigest()[
        :12
    ]
    return f"p_{document_id}_{parent_idx}_{h}"


def _cid(document_id: str, version_id: str, parent_id: str, child_idx: int, text: str) -> str:
    h = hashlib.sha1(f"child|{parent_id}|{child_idx}|{text}".encode()).hexdigest()[:12]
    return f"c_{document_id}_{child_idx}_{h}"


def split_parent_child(
    text: str,
    *,
    document_id: str,
    version_id: str,
    title: str,
    source_path: str = "",
    parent_max: int = 1500,
    child_max: int = 400,
    child_overlap: int = 60,
) -> tuple[list[DocumentChunk], list[DocumentChunk]]:
    """返回 (parents, children)。子块 metadata 含 parent_id 与 parent_text。"""
    from app.rag.chunking import _window

    parents: list[DocumentChunk] = []
    children: list[DocumentChunk] = []
    parent_pieces = _window(text.strip(), max_chars=parent_max, overlap=120)
    for p_idx, parent_text in enumerate(parent_pieces):
        if not parent_text.strip():
            continue
        pid = _pid(document_id, version_id, p_idx, parent_text)
        parents.append(
            DocumentChunk(
                document_id=document_id,
                version_id=version_id,
                chunk_id=pid,
                text=parent_text,
                title=title,
                source_path=source_path,
                metadata={"chunk_role": "parent", "parent_index": p_idx},
            )
        )
        child_pieces = _window(parent_text, max_chars=child_max, overlap=child_overlap)
        for c_idx, child_text in enumerate(child_pieces):
            if not child_text.strip():
                continue
            cid = _cid(document_id, version_id, pid, c_idx, child_text)
            children.append(
                DocumentChunk(
                    document_id=document_id,
                    version_id=version_id,
                    chunk_id=cid,
                    text=child_text,
                    title=title,
                    source_path=source_path,
                    metadata={
                        "chunk_role": "child",
                        "parent_id": pid,
                        "parent_text": parent_text,
                        "parent_index": p_idx,
                        "child_index": c_idx,
                    },
                )
            )
    return parents, children


def expand_child_to_parent(chunk_payload: dict[str, Any]) -> dict[str, Any]:
    """检索到子块时，用父块文本扩充上下文。"""
    role = chunk_payload.get("chunk_role")
    if role == "child" and chunk_payload.get("parent_text"):
        expanded = dict(chunk_payload)
        expanded["text"] = str(chunk_payload["parent_text"])
        expanded["retrieval_expanded"] = True
        return expanded
    return chunk_payload
