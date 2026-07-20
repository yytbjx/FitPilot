"""纯文本 / Markdown 类。"""

from __future__ import annotations

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


@register(".md", ".markdown", ".txt", ".text", ".rst", ".log")
def parse_plain_text(path: Path) -> ParseResult:
    text = _read_text(path).strip()
    return ParseResult(
        title=path.stem,
        text=text,
        format=path.suffix.lower().lstrip(".") or "txt",
        metadata={"encoding_note": "auto"},
    )
