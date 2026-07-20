"""HTML / XML。"""

from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree as ET

from app.rag.parsing.base import ParseError, ParseResult
from app.rag.parsing.registry import register


def _read_bytes_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


@register(".html", ".htm", ".xhtml")
def parse_html(path: Path) -> ParseResult:
    html = _read_bytes_text(path)
    title = path.stem
    text = ""
    try:
        from bs4 import BeautifulSoup  # type: ignore

        soup = None
        for parser_name in ("lxml", "html.parser"):
            try:
                soup = BeautifulSoup(html, parser_name)
                break
            except Exception:
                continue
        if soup is None:
            raise ImportError("no html parser")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        if soup.title and soup.title.get_text(strip=True):
            title = soup.title.get_text(strip=True)
        for level in range(1, 7):
            for h in soup.find_all(f"h{level}"):
                label = h.get_text(" ", strip=True)
                h.clear()
                h.append(f"\n{'#' * level} {label}\n")
        text = soup.get_text("\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)
    except Exception:
        text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
        text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
        text = re.sub(r"(?s)<[^>]+>", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

    body = f"# {title}\n\n{text}".strip()
    if len(body) < 10:
        raise ParseError("html_empty")
    return ParseResult(
        title=title,
        text=body,
        format="html",
    )


@register(".xml")
def parse_xml(path: Path) -> ParseResult:
    raw = _read_bytes_text(path)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ParseError(f"xml_invalid:{exc}") from exc

    lines: list[str] = [f"# {path.stem}", f"Root: {root.tag}"]

    def walk(node: ET.Element, depth: int = 0) -> None:
        indent = "  " * depth
        text = (node.text or "").strip()
        attrs = " ".join(f'{k}="{v}"' for k, v in node.attrib.items())
        head = f"{indent}- {node.tag}"
        if attrs:
            head += f" ({attrs})"
        if text:
            head += f": {text}"
        lines.append(head)
        for child in list(node)[:200]:
            walk(child, depth + 1)

    walk(root)
    text = "\n".join(lines)
    return ParseResult(title=path.stem, text=text, format="xml")
