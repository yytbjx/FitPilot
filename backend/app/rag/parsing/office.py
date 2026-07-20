"""Office：DOCX / PPTX / XLSX。"""

from __future__ import annotations

import os
from pathlib import Path

from app.rag.parsing.base import ParseError, ParseResult
from app.rag.parsing.registry import register


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    if not headers:
        return ""
    esc = [h.replace("|", "\\|") or " " for h in headers]
    lines = [
        "| " + " | ".join(esc) + " |",
        "| " + " | ".join("---" for _ in esc) + " |",
    ]
    for row in rows:
        cells = [(row[i] if i < len(row) else "").replace("|", "\\|").replace("\n", " ") for i in range(len(esc))]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


@register(".docx")
def parse_docx(path: Path) -> ParseResult:
    try:
        from docx import Document  # type: ignore
        from docx.table import Table  # type: ignore
        from docx.text.paragraph import Paragraph  # type: ignore
    except ImportError as exc:
        raise ParseError("python-docx not installed") from exc

    doc = Document(str(path))
    parts: list[str] = []

    # 段落 + 浮动表格按文档顺序（body 元素）
    try:
        body = doc.element.body
        for child in body.iterchildren():
            tag = child.tag.lower()
            if tag.endswith("}p"):
                para = Paragraph(child, doc)
                t = (para.text or "").strip()
                if t:
                    parts.append(t)
            elif tag.endswith("}tbl"):
                table = Table(child, doc)
                headers: list[str] = []
                rows: list[list[str]] = []
                for ri, row in enumerate(table.rows):
                    cells = [(c.text or "").strip() for c in row.cells]
                    if ri == 0:
                        headers = cells or [f"col{i+1}" for i in range(len(cells))]
                    else:
                        rows.append(cells)
                if headers:
                    parts.append(_md_table(headers, rows))
    except Exception:
        # 回退：仅段落
        parts = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
        for ti, table in enumerate(doc.tables, 1):
            headers = [(c.text or "").strip() for c in table.rows[0].cells] if table.rows else []
            rows = [[(c.text or "").strip() for c in r.cells] for r in table.rows[1:]]
            if headers:
                parts.append(f"### Table {ti}\n" + _md_table(headers, rows))

    text = "\n\n".join(parts).strip()
    if not text:
        raise ParseError("docx_empty")
    return ParseResult(title=path.stem, text=f"# {path.stem}\n\n{text}", format="docx")


@register(".pptx")
def parse_pptx(path: Path) -> ParseResult:
    try:
        from pptx import Presentation  # type: ignore
    except ImportError as exc:
        raise ParseError("python-pptx not installed；请 uv add python-pptx") from exc

    prs = Presentation(str(path))
    slides: list[str] = []
    for i, slide in enumerate(prs.slides, 1):
        lines: list[str] = [f"## Slide {i}"]
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text and shape.text.strip():
                lines.append(shape.text.strip())
            if shape.has_table:
                table = shape.table
                headers = [cell.text.strip() for cell in table.rows[0].cells]
                rows = [
                    [cell.text.strip() for cell in row.cells]
                    for row in list(table.rows)[1:]
                ]
                lines.append(_md_table(headers, rows))
        if len(lines) > 1:
            slides.append("\n\n".join(lines))
    text = "\n\n".join(slides).strip()
    if not text:
        raise ParseError("pptx_empty")
    return ParseResult(title=path.stem, text=f"# {path.stem}\n\n{text}", format="pptx")


@register(".xlsx", ".xls")
def parse_xlsx(path: Path) -> ParseResult:
    if path.suffix.lower() == ".xls":
        # openpyxl 不支持老 xls；尽量提示
        raise ParseError("xls_legacy_unsupported_use_xlsx")
    try:
        from openpyxl import load_workbook  # type: ignore
    except ImportError as exc:
        raise ParseError("openpyxl not installed；请 uv add openpyxl") from exc

    max_rows = int(os.getenv("RAG_SHEET_MAX_ROWS", "200") or "200")
    max_sheets = int(os.getenv("RAG_SHEET_MAX_SHEETS", "10") or "10")

    wb = load_workbook(str(path), read_only=True, data_only=True)
    parts: list[str] = [f"# {path.stem}"]
    for si, name in enumerate(wb.sheetnames[:max_sheets]):
        ws = wb[name]
        parts.append(f"## Sheet: {name}")
        rows_iter = ws.iter_rows(values_only=True)
        try:
            header_row = next(rows_iter)
        except StopIteration:
            continue
        headers = [str(c) if c is not None else "" for c in header_row]
        data_rows: list[list[str]] = []
        for ri, row in enumerate(rows_iter):
            if ri >= max_rows:
                parts.append(f"> 已截断：本表仅取前 {max_rows} 行（RAG_SHEET_MAX_ROWS）")
                break
            data_rows.append(["" if c is None else str(c) for c in row])
        if any(headers):
            parts.append(_md_table(headers, data_rows))
    wb.close()
    text = "\n\n".join(parts).strip()
    if len(text) < 20:
        raise ParseError("xlsx_empty")
    return ParseResult(title=path.stem, text=text, format="xlsx")
