"""多格式解析包：导入即完成后缀注册。"""

from __future__ import annotations

from . import data_tabular as data_tabular  # noqa: F401
from . import image_parser as image_parser  # noqa: F401
from . import office as office  # noqa: F401
from . import pdf_parser as pdf_parser  # noqa: F401
from . import text_plain as text_plain  # noqa: F401
from . import web as web  # noqa: F401
from .base import ParseError, ParseResult
from .registry import (
    describe_formats,
    iter_source_files,
    parse_path,
    supported_suffixes,
)


def parse_file(path) -> tuple[str, str]:
    """兼容旧接口：返回 (title, text)。"""
    from pathlib import Path

    return parse_path(Path(path)).as_tuple()


def parse_file_rich(path) -> ParseResult:
    from pathlib import Path

    return parse_path(Path(path))


__all__ = [
    "ParseError",
    "ParseResult",
    "describe_formats",
    "iter_source_files",
    "parse_file",
    "parse_file_rich",
    "parse_path",
    "supported_suffixes",
]
