"""七层评估：食谱/膳食层（Layer 6）。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.services.diet_plan_validator import validate_diet_plan
from app.services.meal_optimizer import meal_macro_totals, optimize_meals


@dataclass
class MealEvalResult:
    total: int = 0
    passed: int = 0
    cases: list[dict[str, Any]] = field(default_factory=list)
    max_kcal_error_pct: float = 0.15
    max_protein_error_pct: float = 0.15
    min_pass_rate: float = 0.8

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def ok(self) -> bool:
        return self.total > 0 and self.pass_rate >= self.min_pass_rate

    def summary_text(self) -> str:
        return (
            f"Meal Eval: {self.passed}/{self.total} pass_rate={self.pass_rate:.2%} "
            f"kcal_err<={self.max_kcal_error_pct:.0%} protein_err<={self.max_protein_error_pct:.0%} "
            f"{'PASS' if self.ok else 'FAIL'}"
        )


def run_meal_eval(suite_path: Path) -> MealEvalResult:
    raw = json.loads(suite_path.read_text(encoding="utf-8"))
    result = MealEvalResult(
        max_kcal_error_pct=float(raw.get("max_kcal_error_pct") or 0.15),
        max_protein_error_pct=float(raw.get("max_protein_error_pct") or 0.15),
        min_pass_rate=float(raw.get("min_pass_rate") or 0.8),
    )
    for case in raw.get("cases") or []:
        foods = case.get("foods") or []
        targets = case.get("targets") or {}
        profile = case.get("profile") or {}
        use_ortools = bool(case.get("use_ortools", True))
        expect_ok = case.get("expect_ok")
        meals = optimize_meals(foods, targets, profile=profile, use_ortools=use_ortools)
        totals = meal_macro_totals(meals)
        target_kcal = float(targets.get("kcal") or 2000)
        target_protein = float(targets.get("protein_g") or 120)
        kcal_err = abs(totals["kcal"] - target_kcal) / max(target_kcal, 1)
        protein_err = abs(totals["protein_g"] - target_protein) / max(target_protein, 1)
        diet_val = validate_diet_plan(profile, {"daily_targets": targets, "meals": meals})
        macro_ok = (
            kcal_err <= result.max_kcal_error_pct
            and protein_err <= result.max_protein_error_pct
        )
        # 忌口：餐品名不应包含 banned 关键词
        banned_raw = f"{profile.get('restrictions') or ''},{profile.get('diet_prefs') or ''}"
        banned = {x.strip().lower() for x in banned_raw.split(",") if x.strip()}
        meal_blob = " ".join(
            str(m.get("name") or m.get("idea") or "")
            + " "
            + " ".join(str(i.get("name") or "") for i in (m.get("items") or []))
            for m in meals
        ).lower()
        ban_ok = not any(b and b in meal_blob for b in banned) if banned else True
        got_ok = macro_ok and bool(diet_val.get("ok")) and ban_ok
        if expect_ok is None:
            ok = got_ok
        else:
            ok = got_ok == bool(expect_ok)
        result.total += 1
        if ok:
            result.passed += 1
        result.cases.append(
            {
                "id": case.get("id"),
                "optimizer": meals[0].get("optimizer") if meals else None,
                "totals": totals,
                "kcal_error_pct": round(kcal_err, 3),
                "protein_error_pct": round(protein_err, 3),
                "diet_ok": bool(diet_val.get("ok")),
                "ban_ok": ban_ok,
                "ok": ok,
            }
        )
    return result
