"""多格式文档解析：统一产出 (title, text)，供切块与入库。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ParseResult:
    """单文件解析结果。"""

    title: str
    text: str
    format: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_tuple(self) -> tuple[str, str]:
        return self.title, self.text


class ParseError(ValueError):
    """无法解析或内容不足以入库。"""
