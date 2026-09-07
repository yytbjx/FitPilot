"""按后缀注册解析器。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app.rag.parsing.base import ParseError, ParseResult

ParserFn = Callable[[Path], ParseResult]

_REGISTRY: dict[str, ParserFn] = {}
_SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".idea",
    ".vscode",
    # 原始网页快照仅作溯源；入库使用 curated/guidelines 清洗后的 Markdown，避免与 HTML 重复切块
    "public_web",
}


def register(*suffixes: str) -> Callable[[ParserFn], ParserFn]:
    """装饰器：注册一个或多个后缀（含点，小写）。"""

    def deco(fn: ParserFn) -> ParserFn:
        for s in suffixes:
            key = s.lower() if s.startswith(".") else f".{s.lower()}"
            _REGISTRY[key] = fn
        return fn

    return deco


def get_parser(suffix: str) -> ParserFn | None:
    key = suffix.lower() if suffix.startswith(".") else f".{suffix.lower()}"
    return _REGISTRY.get(key)


def supported_suffixes() -> list[str]:
    return sorted(_REGISTRY.keys())


def describe_formats() -> list[dict[str, str]]:
    """给人看的格式清单（用于 API / 文档）。"""
    groups = {
        "text": [".md", ".markdown", ".txt", ".text", ".rst", ".log"],
        "office": [".docx", ".pptx", ".xlsx", ".xls"],
        "pdf": [".pdf"],
        "web": [".html", ".htm", ".xhtml", ".xml"],
        "data": [".csv", ".tsv", ".json", ".jsonl", ".ndjson"],
        "image": [".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"],
    }
    out: list[dict[str, str]] = []
    for group, suffixes in groups.items():
        for s in suffixes:
            if s in _REGISTRY:
                out.append({"suffix": s, "group": group})
    # 兜底：登记了但未进分组的
    known = {x["suffix"] for x in out}
    for s in supported_suffixes():
        if s not in known:
            out.append({"suffix": s, "group": "other"})
    return out


def should_skip_path(path: Path, *, root: Path | None = None) -> bool:
    parts = set(path.parts)
    if parts & _SKIP_DIR_NAMES:
        return True
    name = path.name.lower()
    if name.startswith("~$"):  # Office 临时锁文件
        return True
    if name.endswith(".tmp") or name.endswith(".bak"):
        return True
    return False


def iter_source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    if root.is_file():
        return [root] if get_parser(root.suffix) and not should_skip_path(root) else []
    if not root.exists():
        return []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if should_skip_path(p, root=root):
            continue
        if get_parser(p.suffix) is None:
            continue
        # 明显损坏的极小 PDF
        if p.suffix.lower() == ".pdf" and p.stat().st_size < 2048:
            continue
        files.append(p)
    return files


def parse_path(path: Path) -> ParseResult:
    parser = get_parser(path.suffix)
    if parser is None:
        raise ParseError(f"unsupported_suffix:{path.suffix.lower()}")
    result = parser(path)
    if not (result.text or "").strip():
        raise ParseError(f"empty_parse:{path.name}")
    return result
