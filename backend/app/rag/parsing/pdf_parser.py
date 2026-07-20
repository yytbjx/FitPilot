"""PDF 解析（可检索文本；扫描件过短则报错）。"""

from __future__ import annotations

import os
from pathlib import Path

from app.rag.parsing.base import ParseError, ParseResult
from app.rag.parsing.registry import register


@register(".pdf")
def parse_pdf(path: Path) -> ParseResult:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        raise ParseError("pypdf not installed") from exc

    max_pages_env = os.getenv("RAG_PDF_MAX_PAGES", "").strip()
    max_pages = int(max_pages_env) if max_pages_env.isdigit() else None

    reader = PdfReader(str(path))
    meta_bits: list[str] = []
    try:
        info = reader.metadata
        if info:
            for key in ("title", "author", "subject"):
                val = getattr(info, key, None) or (info.get(f"/{key.title()}") if hasattr(info, "get") else None)
                if val:
                    meta_bits.append(f"{key}: {val}")
    except Exception:
        pass

    pages: list[str] = []
    total = len(reader.pages)
    limit = min(total, max_pages) if max_pages else total
    for i in range(limit):
        page = reader.pages[i]
        try:
            t = (page.extract_text() or "").strip()
        except Exception:
            t = ""
        if t:
            pages.append(f"## Page {i + 1}\n{t}")

    body = "\n\n".join(pages).strip()
    if len(body) < 40:
        raise ParseError("pdf_text_too_short_or_scanned")

    header = f"# {path.stem}\n\n"
    if meta_bits:
        header += "## Document Metadata\n" + "\n".join(f"- {b}" for b in meta_bits) + "\n\n"
    if max_pages and total > limit:
        header += f"> 已截断：共 {total} 页，仅解析前 {limit} 页（RAG_PDF_MAX_PAGES）\n\n"

    return ParseResult(
        title=path.stem,
        text=header + body,
        format="pdf",
        metadata={"pages_parsed": limit, "pages_total": total},
    )
