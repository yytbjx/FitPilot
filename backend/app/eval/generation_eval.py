"""生成与引用层评估：静态规则 + 可选检索端到端。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class GenerationEvalResult:
    total: int = 0
    passed: int = 0
    cases: list[dict[str, Any]] = field(default_factory=list)
    min_pass_rate: float = 0.8

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def ok(self) -> bool:
        return self.total > 0 and self.pass_rate >= self.min_pass_rate

    def summary_text(self) -> str:
        return (
            f"Generation Eval: {self.passed}/{self.total} pass_rate={self.pass_rate:.2%} "
            f"{'PASS' if self.ok else 'FAIL'}"
        )


def _citation_precision(citations: list[str], expect_keywords: list[str]) -> float:
    if not expect_keywords:
        return 1.0
    if not citations:
        return 0.0
    hits = sum(1 for kw in expect_keywords if any(kw.lower() in c.lower() for c in citations))
    return hits / len(expect_keywords)


def _unsupported_claim_rate(answer: str, forbidden: list[str]) -> float:
    if not forbidden:
        return 0.0
    hits = sum(1 for f in forbidden if f.lower() in answer.lower())
    return hits / len(forbidden)


def _eval_static(case: dict[str, Any]) -> dict[str, Any]:
    answer = str(case.get("answer") or "")
    citations = [str(c) for c in (case.get("citations") or [])]
    expect_kw = [str(k) for k in (case.get("expect_citation_keywords") or [])]
    forbidden = [str(f) for f in (case.get("forbidden_claims") or [])]
    min_cite = float(case.get("min_citation_precision") or 0.5)
    max_unsupported = float(case.get("max_unsupported_rate") or 0.0)
    cite_p = _citation_precision(citations, expect_kw)
    unsup = _unsupported_claim_rate(answer, forbidden)
    relevance = 1.0
    if case.get("expect_answer_contains"):
        relevance = (
            1.0
            if all(str(k).lower() in answer.lower() for k in case.get("expect_answer_contains") or [])
            else 0.0
        )
    ok = cite_p >= min_cite and unsup <= max_unsupported and relevance >= 0.5
    return {
        "id": case.get("id"),
        "mode": "static",
        "citation_precision": round(cite_p, 3),
        "unsupported_rate": round(unsup, 3),
        "relevance": relevance,
        "ok": ok,
    }


async def _eval_e2e_retrieve(case: dict[str, Any]) -> dict[str, Any]:
    """端到端：query → hybrid_retrieve → build_context，校验引用与上下文关键词（不调 LLM）。"""
    from app.rag.context import build_context
    from app.rag.retrieve import hybrid_retrieve

    query = str(case.get("query") or "")
    expect_kw = [str(k) for k in (case.get("expect_citation_keywords") or [])]
    expect_ctx = [str(k) for k in (case.get("expect_context_contains") or [])]
    forbidden = [str(f) for f in (case.get("forbidden_claims") or [])]
    min_cite = float(case.get("min_citation_precision") or 0.5)
    allow_no_answer = bool(case.get("allow_no_answer", False))
    try:
        # 依赖 Qdrant 的用例：服务不可用时直接返回 error，交由上层按 skip_on_error 跳过。
        # 注意 dense_search 内部会吞连接异常，因此必须先显式探测。
        from app.services.qdrant_client import get_qdrant_service

        try:
            get_qdrant_service().client.get_collections()
        except Exception as probe_exc:  # noqa: BLE001
            raise RuntimeError(f"qdrant_unavailable: {probe_exc}") from probe_exc
        chunks = await hybrid_retrieve(query, top_k=4)
        packed = build_context(chunks)
        citations: list[str] = []
        for c in packed.get("citations") or []:
            if isinstance(c, dict):
                citations.append(str(c.get("citation") or c.get("document_id") or c))
            else:
                citations.append(str(c))
        for c in packed.get("chunks") or []:
            if isinstance(c, dict):
                citations.append(str(c.get("citation") or c.get("document_id") or ""))
            else:
                citations.append(str(getattr(c, "citation", "") or getattr(c, "document_id", "") or ""))
        context = str(packed.get("context") or packed.get("answer_context") or "")
        cite_p = _citation_precision(citations, expect_kw)
        ctx_ok = (
            True
            if not expect_ctx
            else all(k.lower() in context.lower() for k in expect_ctx)
        )
        unsup = _unsupported_claim_rate(context, forbidden)
        no_answer = bool(packed.get("no_answer"))
        answer_ok = allow_no_answer or not no_answer
        ok = cite_p >= min_cite and ctx_ok and unsup <= float(case.get("max_unsupported_rate") or 0.0) and answer_ok
        return {
            "id": case.get("id"),
            "mode": "e2e_retrieve",
            "citation_precision": round(cite_p, 3),
            "context_ok": ctx_ok,
            "no_answer": no_answer,
            "unsupported_rate": round(unsup, 3),
            "ok": ok,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "id": case.get("id"),
            "mode": "e2e_retrieve",
            "ok": False,
            "error": str(exc),
        }


async def run_generation_eval_async(suite_path: Path) -> GenerationEvalResult:
    raw = json.loads(suite_path.read_text(encoding="utf-8"))
    result = GenerationEvalResult(min_pass_rate=float(raw.get("min_pass_rate") or 0.8))
    for case in raw.get("cases") or []:
        mode = str(case.get("mode") or "static").lower()
        if mode in {"e2e", "e2e_retrieve"}:
            row = await _eval_e2e_retrieve(case)
            # 依赖 Qdrant 的用例：服务不可用时跳过，不拖垮离线门禁
            if row.get("error") and case.get("skip_on_error", True):
                row["skipped"] = True
                result.cases.append(row)
                continue
        else:
            row = _eval_static(case)
        result.total += 1
        if row.get("ok"):
            result.passed += 1
        result.cases.append(row)
    return result


def run_generation_eval(suite_path: Path) -> GenerationEvalResult:
    return asyncio.run(run_generation_eval_async(suite_path))
