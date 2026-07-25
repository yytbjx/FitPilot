"""七层评估：训练计划层（Layer 5）。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.eval.common import PassRateEvalResult
from app.services.training_plan_validator import validate_training_plan


@dataclass
class PlanEvalResult(PassRateEvalResult):
    min_pass_rate: float = 0.9
    label: str = "Plan Eval"


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
