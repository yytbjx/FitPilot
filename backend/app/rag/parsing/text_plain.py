"""纯文本 / Markdown 类。"""

from __future__ import annotations

import re
from pathlib import Path

from app.rag.parsing.base import ParseResult
from app.rag.parsing.registry import register


def _read_text(path: Path) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_bytes().decode("utf-8", errors="ignore")


def _title_from_markdown(text: str, fallback: str) -> str:
    for line in text.splitlines():
        m = re.match(r"^#\s+(.+)$", line.strip())
        if m:
            return m.group(1).strip()
    return fallback


@register(".md", ".markdown", ".txt", ".text", ".rst", ".log")
def parse_plain_text(path: Path) -> ParseResult:
    text = _read_text(path).strip()
    fmt = path.suffix.lower().lstrip(".") or "txt"
    title = path.stem
    if fmt in {"md", "markdown"}:
        title = _title_from_markdown(text, path.stem)
    return ParseResult(
        title=title,
        text=text,
        format=fmt,
        metadata={"encoding_note": "auto"},
    )
