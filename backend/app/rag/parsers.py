"""文档解析兼容层：转发到 app.rag.parsing 多格式实现。"""

from __future__ import annotations

from app.rag.parsing import (
    ParseError,
    ParseResult,
    describe_formats,
    iter_source_files,
    parse_file,
    parse_file_rich,
    parse_path,
    supported_suffixes,
)

# 旧常量（近似；以 registry 为准）
SUPPORTED_SUFFIXES = {
    ".md",
    ".markdown",
    ".txt",
    ".text",
    ".rst",
    ".log",
    ".docx",
    ".pptx",
    ".xlsx",
    ".pdf",
    ".html",
    ".htm",
    ".xhtml",
    ".xml",
    ".csv",
    ".tsv",
    ".json",
    ".jsonl",
    ".ndjson",
}
IMAGE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
}

__all__ = [
    "IMAGE_SUFFIXES",
    "ParseError",
    "ParseResult",
    "SUPPORTED_SUFFIXES",
    "describe_formats",
    "iter_source_files",
    "parse_file",
    "parse_file_rich",
    "parse_path",
    "supported_suffixes",
]
