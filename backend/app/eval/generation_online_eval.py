"""生成层在线评估：LLM-as-judge（Faithfulness / Relevance）。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.eval.progress import track_cases
from app.services.ollama_client import get_ollama_client


@dataclass
class GenerationOnlineResult:
    total: int = 0
    passed: int = 0
    cases: list[dict[str, Any]] = field(default_factory=list)
    min_faithfulness: float = 0.7
    min_relevance: float = 0.7
    min_pass_rate: float = 0.8
    used_llm: bool = False

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def ok(self) -> bool:
        return self.total > 0 and self.pass_rate >= self.min_pass_rate

    def summary_text(self) -> str:
        return (
            f"Generation Online (LLM judge): {self.passed}/{self.total} "
            f"pass_rate={self.pass_rate:.2%} llm={self.used_llm} "
            f"{'PASS' if self.ok else 'FAIL'}"
        )


def _parse_scores(text: str) -> tuple[float, float]:
    """从 judge 输出解析 faithfulness / relevance。"""
    faith = rel = 0.0
    m1 = re.search(r"faithfulness\s*[:=]\s*([0-9.]+)", text, re.I)
    m2 = re.search(r"relevance\s*[:=]\s*([0-9.]+)", text, re.I)
    if m1:
        faith = float(m1.group(1))
    if m2:
        rel = float(m2.group(1))
    if faith == 0 and rel == 0:
        nums = re.findall(r"0?\.\d+|1\.0|1", text)
        if len(nums) >= 2:
            faith, rel = float(nums[0]), float(nums[1])
    return min(max(faith, 0.0), 1.0), min(max(rel, 0.0), 1.0)


async def run_generation_online_eval_async(suite_path: Path) -> GenerationOnlineResult:
    raw = json.loads(suite_path.read_text(encoding="utf-8"))
    result = GenerationOnlineResult(
        min_faithfulness=float(raw.get("min_faithfulness") or 0.7),
        min_relevance=float(raw.get("min_relevance") or 0.7),
        min_pass_rate=float(raw.get("min_pass_rate") or 0.8),
    )
    client = get_ollama_client()
    result.used_llm = True

    for case in track_cases(list(raw.get("cases") or []), desc="generation_online"):
        question = str(case.get("question") or "")
        context = str(case.get("context") or "")
        answer = str(case.get("answer") or "")
        prompt = (
            "你是 RAG 评估裁判。根据【证据】判断【回答】是否忠实、是否相关。\n"
            "只输出两行：faithfulness: 0-1 数字\nrelevance: 0-1 数字\n\n"
            f"问题：{question}\n证据：{context}\n回答：{answer}"
        )
        try:
            resp = await client.chat(
                [
                    {"role": "system", "content": "严格 JSON 风格分数输出"},
                    {"role": "user", "content": prompt},
                ],
                role="judge",
                options={"num_predict": 64, "temperature": 0.0},
            )
            judge_text = (resp.get("message") or {}).get("content") or ""
            faith, rel = _parse_scores(judge_text)
        except Exception as exc:  # noqa: BLE001
            faith, rel = 0.0, 0.0
            judge_text = str(exc)
            result.used_llm = False

        scored_ok = faith >= result.min_faithfulness and rel >= result.min_relevance
        # expect_fail=true：期望裁判识别为不忠实/不相关
        expect_fail = bool(case.get("expect_fail"))
        ok = (not scored_ok) if expect_fail else scored_ok
        result.total += 1
        if ok:
            result.passed += 1
        result.cases.append(
            {
                "id": case.get("id"),
                "faithfulness": round(faith, 3),
                "relevance": round(rel, 3),
                "expect_fail": expect_fail,
                "scored_ok": scored_ok,
                "ok": ok,
                "judge_raw": judge_text[:500],
            }
        )
    return result


def run_generation_online_eval(suite_path: Path) -> GenerationOnlineResult:
    import asyncio

    return asyncio.run(run_generation_online_eval_async(suite_path))
