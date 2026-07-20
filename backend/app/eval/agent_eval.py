"""Agent 路由与计划生成评估（规则层）。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.graphs.fitness_graph import classify_intent, is_complex_task


@dataclass
class AgentEvalResult:
    total: int = 0
    correct: int = 0
    cases: list[dict[str, Any]] = field(default_factory=list)
    min_accuracy: float = 0.85
    min_macro_f1: float = 0.8

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def macro_f1(self) -> float:
        labels: set[str] = set()
        for c in self.cases:
            if c.get("expect_intent"):
                labels.add(str(c["expect_intent"]))
            if c.get("got_intent"):
                labels.add(str(c["got_intent"]))
        if not labels:
            return 0.0
        f1s: list[float] = []
        for label in labels:
            tp = sum(
                1
                for c in self.cases
                if c.get("got_intent") == label and c.get("expect_intent") == label
            )
            fp = sum(
                1
                for c in self.cases
                if c.get("got_intent") == label and c.get("expect_intent") != label
            )
            fn = sum(
                1
                for c in self.cases
                if c.get("got_intent") != label and c.get("expect_intent") == label
            )
            prec = tp / (tp + fp) if (tp + fp) else 0.0
            rec = tp / (tp + fn) if (tp + fn) else 0.0
            f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
            f1s.append(f1)
        return sum(f1s) / len(f1s)

    @property
    def ok(self) -> bool:
        return (
            self.total > 0
            and self.accuracy >= self.min_accuracy
            and self.macro_f1 >= self.min_macro_f1
        )

    def summary_text(self) -> str:
        return (
            f"Agent Eval: {self.correct}/{self.total} acc={self.accuracy:.2%} "
            f"macro_f1={self.macro_f1:.2%} (min_acc={self.min_accuracy:.0%} "
            f"min_f1={self.min_macro_f1:.0%}) {'PASS' if self.ok else 'FAIL'}"
        )


def run_agent_eval(suite_path: Path) -> AgentEvalResult:
    raw = json.loads(suite_path.read_text(encoding="utf-8"))
    min_acc = float(raw.get("min_accuracy") or 0.85)
    min_f1 = float(raw.get("min_macro_f1") or 0.8)
    result = AgentEvalResult(min_accuracy=min_acc, min_macro_f1=min_f1)
    for case in raw.get("cases") or []:
        text = str(case.get("message") or "")
        expect_intent = str(case.get("expect_intent") or "")
        expect_complex = case.get("expect_complex")
        got_intent = classify_intent(text)
        got_complex = is_complex_task(text, got_intent)  # type: ignore[arg-type]
        intent_ok = got_intent == expect_intent
        complex_ok = True if expect_complex is None else bool(got_complex) == bool(expect_complex)
        correct = intent_ok and complex_ok
        result.total += 1
        if correct:
            result.correct += 1
        result.cases.append(
            {
                "id": case.get("id"),
                "message": text,
                "expect_intent": expect_intent,
                "got_intent": got_intent,
                "expect_complex": expect_complex,
                "got_complex": got_complex,
                "correct": correct,
            }
        )
    return result
