"""评估模块公共基类：消除 meal/plan/safety/parsing/generation 中逐字重复的 Result 结构。

行为约定（与原各模块一致）：
- total/passed/cases/min_pass_rate 字段；
- pass_rate = passed / total（total 为 0 时 0.0）；
- ok = total > 0 且 pass_rate >= min_pass_rate；
- summary_text 输出 "<label>: <passed>/<total> pass_rate=<pct> [extra] PASS|FAIL"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PassRateEvalResult:
    """pass_rate 门禁类评估结果基类。"""

    total: int = 0
    passed: int = 0
    cases: list[dict[str, Any]] = field(default_factory=list)
    min_pass_rate: float = 0.8
    label: str = "Eval"

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def ok(self) -> bool:
        return self.total > 0 and self.pass_rate >= self.min_pass_rate

    def _extra_summary(self) -> str:
        """子类可覆盖：追加到 summary 的额外信息（空串表示无）。"""
        return ""

    def summary_text(self) -> str:
        parts = [f"{self.label}: {self.passed}/{self.total} pass_rate={self.pass_rate:.2%}"]
        extra = self._extra_summary()
        if extra:
            parts.append(extra)
        parts.append("PASS" if self.ok else "FAIL")
        return " ".join(parts)
