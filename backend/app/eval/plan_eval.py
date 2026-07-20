"""七层评估：训练计划层（Layer 5）。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.services.training_plan_validator import validate_training_plan


@dataclass
class PlanEvalResult:
    total: int = 0
    passed: int = 0
    cases: list[dict[str, Any]] = field(default_factory=list)
    min_pass_rate: float = 0.9

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def ok(self) -> bool:
        return self.total > 0 and self.pass_rate >= self.min_pass_rate

    def summary_text(self) -> str:
        return (
            f"Plan Eval: {self.passed}/{self.total} pass_rate={self.pass_rate:.2%} "
            f"{'PASS' if self.ok else 'FAIL'}"
        )


def run_plan_eval(suite_path: Path) -> PlanEvalResult:
    raw = json.loads(suite_path.read_text(encoding="utf-8"))
    result = PlanEvalResult(min_pass_rate=float(raw.get("min_pass_rate") or 0.9))
    for case in raw.get("cases") or []:
        profile = case.get("profile") or {}
        workout = case.get("workout") or {}
        expect_ok = bool(case.get("expect_ok", True))
        val = validate_training_plan(profile, workout)
        ok = bool(val.get("ok")) == expect_ok
        result.total += 1
        if ok:
            result.passed += 1
        result.cases.append(
            {
                "id": case.get("id"),
                "expect_ok": expect_ok,
                "got_ok": bool(val.get("ok")),
                "errors": val.get("errors"),
                "warnings": val.get("warnings"),
                "ok": ok,
            }
        )
    return result
