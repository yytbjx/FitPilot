"""无答案/拒答评估。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.eval.progress import track_cases
from app.rag.context import build_context
from app.rag.retrieve import hybrid_retrieve


@dataclass
class NoAnswerEvalResult:
    total: int = 0
    correct: int = 0
    true_positive: int = 0
    false_positive: int = 0
    false_negative: int = 0
    cases: list[dict[str, Any]] = field(default_factory=list)
    min_recall: float = 0.8
    min_precision: float = 0.7

    @property
    def recall(self) -> float:
        denom = self.true_positive + self.false_negative
        return self.true_positive / denom if denom else 0.0

    @property
    def precision(self) -> float:
        denom = self.true_positive + self.false_positive
        return self.true_positive / denom if denom else 0.0

    @property
    def ok(self) -> bool:
        return (
            self.total > 0
            and self.recall >= self.min_recall
            and self.precision >= self.min_precision
        )

    def summary_text(self) -> str:
        return (
            f"No-Answer Eval: {self.correct}/{self.total} "
            f"recall={self.recall:.2%} precision={self.precision:.2%} "
            f"{'PASS' if self.ok else 'FAIL'}"
        )


async def run_no_answer_eval_async(suite_path: Path) -> NoAnswerEvalResult:
    raw = json.loads(suite_path.read_text(encoding="utf-8"))
    min_recall = float(raw.get("min_no_answer_recall") or 0.8)
    min_precision = float(raw.get("min_no_answer_precision") or 0.7)
    result = NoAnswerEvalResult(min_recall=min_recall, min_precision=min_precision)
    for case in track_cases(list(raw.get("cases") or []), desc="no_answer"):
        q = str(case.get("query") or "")
        expect = bool(case.get("expect_no_answer", True))
        chunks = await hybrid_retrieve(q, top_k=4)
        packed = build_context(chunks)
        got_no_answer = bool(packed.get("no_answer"))
        correct = got_no_answer == expect
        if expect and got_no_answer:
            result.true_positive += 1
        elif expect and not got_no_answer:
            result.false_negative += 1
        elif not expect and got_no_answer:
            result.false_positive += 1
        result.total += 1
        if correct:
            result.correct += 1
        result.cases.append(
            {
                "id": case.get("id"),
                "query": q,
                "expect_no_answer": expect,
                "got_no_answer": got_no_answer,
                "reason": packed.get("reason"),
                "correct": correct,
            }
        )
    return result


def run_no_answer_eval(suite_path: Path) -> NoAnswerEvalResult:
    import asyncio

    return asyncio.run(run_no_answer_eval_async(suite_path))
