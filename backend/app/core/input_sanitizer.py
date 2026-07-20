"""输入安全过滤（迁移自 llm-knowledge-base，去掉对其 tracing 的硬依赖）。"""

from __future__ import annotations

import re
from typing import Optional

_INJECTION_PATTERNS = [
    r"ignore previous instructions",
    r"ignore all (above|previous)",
    r"you are now .*? instead",
    r"new instructions?:",
    r"system prompt",
    r"DAN mode",
    r"jailbreak",
    r"\[system\]",
    r"\[admin\]",
    r"\[developer\]",
    r"忽略(以上|之前|之前的)?(所有)?(指令|提示|规则)",
    r"你现在是",
]

_DANGEROUS_KEYWORDS = [
    "rm -rf",
    "delete all",
    "drop table",
    "format c:",
    "shutdown",
    "reboot",
    "exec(",
    "eval(",
]


class InputSanitizer:
    def __init__(self, max_length: int = 5000) -> None:
        self.max_length = max_length

    def sanitize(self, text: str) -> tuple[str, Optional[str]]:
        if not text or not str(text).strip():
            return "", "输入不能为空"
        text = str(text)
        if len(text) > self.max_length:
            return "", f"输入过长（{len(text)} > {self.max_length}）"
        lower = text.lower()
        for pattern in _INJECTION_PATTERNS:
            if re.search(pattern, lower, flags=re.I):
                return "", f"检测到疑似 Prompt Injection：{pattern}"
        for keyword in _DANGEROUS_KEYWORDS:
            if keyword in lower:
                return "", f"检测到危险指令：{keyword}"
        return self._strip_zwc(text), None

    @staticmethod
    def _strip_zwc(text: str) -> str:
        for c in "\u200b\u200c\u200d\ufeff\u2060\u2061\u2062\u2063":
            text = text.replace(c, "")
        return text


_sanitizer: InputSanitizer | None = None


def get_sanitizer() -> InputSanitizer:
    global _sanitizer
    if _sanitizer is None:
        _sanitizer = InputSanitizer()
    return _sanitizer
