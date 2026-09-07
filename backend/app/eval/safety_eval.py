"""七层评估：安全与联合调整层（Layer 7）。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.eval.common import PassRateEvalResult
from app.eval.progress import track_cases
from app.services.weekly_adjustment import build_weekly_adjustment, diagnose_week
from app.tools.domain import check_risk


@dataclass
class SafetyEvalResult(PassRateEvalResult):
    min_pass_rate: float = 0.9
    label: str = "Safety Eval"


def run_safety_eval(suite_path: Path) -> SafetyEvalResult:
    raw = json.loads(suite_path.read_text(encoding="utf-8"))
    result = SafetyEvalResult(min_pass_rate=float(raw.get("min_pass_rate") or 0.9))
    for case in track_cases(list(raw.get("cases") or []), desc="safety"):
        kind = str(case.get("kind") or "risk")
        ok = False
        detail: dict[str, Any] = {}
        if kind == "risk":
            text = str(case.get("text") or "")
            expect_level = str(case.get("expect_risk_level") or "low")
            got = check_risk(text)
            ok = got.get("risk_level") == expect_level
            detail = {"got": got.get("risk_level"), "expect": expect_level}
        elif kind == "weekly_alignment":
            profile = case.get("profile") or {}
            logs = case.get("logs") or {}
            workout = case.get("workout") or {"days": []}
            diet = case.get("diet") or {"daily_targets": {}, "meals": []}
            diag = diagnose_week(profile, logs)
            adjusted = build_weekly_adjustment(profile, logs, dict(workout), dict(diet))
            expect_issues = case.get("expect_issues") or []
            issues = diag.get("issues") or []
            issue_ok = all(i in issues for i in expect_issues) if expect_issues else True
            alignment_ok = bool(adjusted.get("workout")) and bool(adjusted.get("diet"))
            ok = issue_ok and alignment_ok
            detail = {"issues": issues, "reason": adjusted.get("reason")}
        result.total += 1
        if ok:
            result.passed += 1
        result.cases.append({"id": case.get("id"), "kind": kind, "ok": ok, **detail})
    return result
