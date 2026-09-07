"""FitPilot RAG 评估：Hit@K / Precision@K / TermRecall@K / MRR / nDCG / 时延。"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.eval.progress import track_cases
from app.rag.context import build_context
from app.rag.retrieve import hybrid_retrieve


@dataclass
class CaseResult:
    id: str
    query: str
    hit: bool
    hit_at_k: dict[str, bool] = field(default_factory=dict)
    first_relevant_rank: int | None = None
    reciprocal_rank: float = 0.0
    citation_present: bool = False
    no_answer: bool = False
    latency_ms: float = 0.0
    matched_terms: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    context_fallback_hit: bool = False
    ndcg_at_k: dict[str, float] = field(default_factory=dict)
    precision_at_k: dict[str, float] = field(default_factory=dict)
    term_recall_at_k: dict[str, float] = field(default_factory=dict)
    anchor_chunk_at_k: dict[str, float] | None = None
    anchor_doc_at_k: dict[str, float] | None = None
    error: str | None = None


@dataclass
class EvalReport:
    suite: str
    cases: list[CaseResult]
    hit_rate: float
    citation_rate: float
    avg_latency_ms: float
    hit_at_k: dict[str, float]
    mrr: float
    ok: bool
    ndcg_at_k: dict[str, float] = field(default_factory=dict)
    precision_at_k: dict[str, float] = field(default_factory=dict)
    term_recall_at_k: dict[str, float] = field(default_factory=dict)
    anchor_chunk_at_k: dict[str, float] = field(default_factory=dict)
    anchor_doc_at_k: dict[str, float] = field(default_factory=dict)
    anchor_chunk_cases: int = 0
    anchor_doc_cases: int = 0
    fallback_hits: int = 0
    thresholds: dict[str, Any] = field(default_factory=dict)

    def summary_text(self) -> str:
        lines = [
            f"suite={self.suite}",
            f"cases={len(self.cases)}",
            f"hit_rate={self.hit_rate:.2%}（严格口径：整包 context 兜底命中单独计数，不计入）",
            f"fallback_hits={self.fallback_hits}",
            f"citation_rate={self.citation_rate:.2%}",
            f"mrr={self.mrr:.4f}",
            f"avg_latency_ms={self.avg_latency_ms:.0f}",
        ]
        for k, v in sorted(self.hit_at_k.items(), key=lambda x: int(x[0].replace("hit@", "") or 0)):
            lines.append(f"{k}={v:.2%}")
        for k, v in sorted(
            self.precision_at_k.items(), key=lambda x: int(x[0].replace("precision@", "") or 0)
        ):
            lines.append(f"{k}={v:.4f}")
        for k, v in sorted(
            self.term_recall_at_k.items(),
            key=lambda x: int(x[0].replace("term_recall@", "") or 0),
        ):
            lines.append(f"{k}={v:.4f}")
        for k, v in sorted(
            self.ndcg_at_k.items(), key=lambda x: int(x[0].replace("ndcg@", "") or 0)
        ):
            lines.append(f"{k}={v:.4f}")
        if self.anchor_chunk_cases:
            lines.append(f"anchor_chunk_cases={self.anchor_chunk_cases}")
            for k, v in sorted(
                self.anchor_chunk_at_k.items(),
                key=lambda x: int(x[0].replace("anchor_chunk@", "") or 0),
            ):
                lines.append(f"{k}={v:.2%}")
        if self.anchor_doc_cases:
            lines.append(f"anchor_doc_cases={self.anchor_doc_cases}")
            for k, v in sorted(
                self.anchor_doc_at_k.items(),
                key=lambda x: int(x[0].replace("anchor_doc@", "") or 0),
            ):
                lines.append(f"{k}={v:.2%}")
        lines.append(f"pass={self.ok}")
        for c in self.cases:
            status = "HIT" if c.hit else ("FALLBACK" if c.context_fallback_hit else "MISS")
            rank = c.first_relevant_rank if c.first_relevant_rank is not None else "-"
            lines.append(
                f"  [{status}] {c.id} rank={rank} {c.latency_ms:.0f}ms cite={c.citation_present} :: {c.query[:40]}"
            )
            if c.error:
                lines.append(f"    error={c.error}")
        return "\n".join(lines)

    def to_markdown(self) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        lines = [
            "# FitPilot RAG Eval Report",
            "",
            f"- generated_at: `{ts}`",
            f"- suite: `{self.suite}`",
            f"- cases: **{len(self.cases)}**",
            f"- hit_rate: **{self.hit_rate:.2%}**（严格口径，fallback_hits={self.fallback_hits} 单独计数）",
            f"- citation_rate: **{self.citation_rate:.2%}**",
            f"- MRR: **{self.mrr:.4f}**",
            f"- avg_latency_ms: **{self.avg_latency_ms:.0f}**",
            f"- pass: **{self.ok}**",
            "",
            "## Hit@K",
            "",
            "| K | rate |",
            "|---|------|",
        ]
        for k, v in sorted(self.hit_at_k.items(), key=lambda x: int(x[0].replace("hit@", "") or 0)):
            lines.append(f"| {k} | {v:.2%} |")
        lines.extend(["", "## Precision@K", "", "| K | value |", "|---|------|"])
        for k, v in sorted(
            self.precision_at_k.items(), key=lambda x: int(x[0].replace("precision@", "") or 0)
        ):
            lines.append(f"| {k} | {v:.4f} |")
        lines.extend(["", "## TermRecall@K", "", "| K | value |", "|---|------|"])
        for k, v in sorted(
            self.term_recall_at_k.items(),
            key=lambda x: int(x[0].replace("term_recall@", "") or 0),
        ):
            lines.append(f"| {k} | {v:.4f} |")
        lines.extend(["", "## nDCG@K", "", "| K | value |", "|---|------|"])
        for k, v in sorted(
            self.ndcg_at_k.items(), key=lambda x: int(x[0].replace("ndcg@", "") or 0)
        ):
            lines.append(f"| {k} | {v:.4f} |")
        if self.anchor_chunk_cases or self.anchor_doc_cases:
            lines.extend(
                [
                    "",
                    "## Anchor Recall@K",
                    "",
                    f"- anchor_chunk_cases: **{self.anchor_chunk_cases}**",
                    f"- anchor_doc_cases: **{self.anchor_doc_cases}**",
                    "",
                    "| metric | value |",
                    "|--------|------|",
                ]
            )
            for k, v in sorted(
                self.anchor_chunk_at_k.items(),
                key=lambda x: int(x[0].replace("anchor_chunk@", "") or 0),
            ):
                lines.append(f"| {k} | {v:.2%} |")
            for k, v in sorted(
                self.anchor_doc_at_k.items(),
                key=lambda x: int(x[0].replace("anchor_doc@", "") or 0),
            ):
                lines.append(f"| {k} | {v:.2%} |")
        lines.extend(
            ["", "## Cases", "", "| id | hit | rank | latency_ms | query |", "|----|-----|------|------------|-------|"]
        )
        for c in self.cases:
            rank = c.first_relevant_rank if c.first_relevant_rank is not None else ""
            q = c.query.replace("|", "/")[:48]
            lines.append(f"| {c.id} | {c.hit} | {rank} | {c.latency_ms:.0f} | {q} |")
        lines.append("")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "hit_rate": self.hit_rate,
            "citation_rate": self.citation_rate,
            "avg_latency_ms": self.avg_latency_ms,
            "hit_at_k": self.hit_at_k,
            "precision_at_k": self.precision_at_k,
            "term_recall_at_k": self.term_recall_at_k,
            "ndcg_at_k": self.ndcg_at_k,
            "anchor_chunk_at_k": self.anchor_chunk_at_k,
            "anchor_doc_at_k": self.anchor_doc_at_k,
            "anchor_chunk_cases": self.anchor_chunk_cases,
            "anchor_doc_cases": self.anchor_doc_cases,
            "fallback_hits": self.fallback_hits,
            "mrr": self.mrr,
            "ok": self.ok,
            "thresholds": self.thresholds,
            "cases": [asdict(c) for c in self.cases],
        }


def _load_suite(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "cases" not in data:
        raise ValueError("评测集需为 { name, cases: [...] }")
    return data


def load_eval_config(path: Path | None) -> dict[str, Any]:
    """统一评估配置加载：YAML 为唯一权威格式（evals/eval_config.yaml）。

    兼容：显式传入 .json 路径时仍按 JSON 解析（仅供临时文件/旧脚本），
    但仓库不再维护 eval_config.json；不再做「同名 .json 回退」。
    """
    if path is None or not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix == ".json":
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    import yaml  # type: ignore

    data = yaml.safe_load(text) or {}
    return data if isinstance(data, dict) else {}


def _chunk_blob(chunk: Any) -> str:
    if isinstance(chunk, dict):
        parts = [
            str(chunk.get("text") or ""),
            str(chunk.get("citation") or ""),
            str(chunk.get("document_id") or ""),
            str(chunk.get("title") or ""),
        ]
        meta = chunk.get("metadata") or {}
        if isinstance(meta, dict):
            parts.append(json.dumps(meta, ensure_ascii=False))
        return "\n".join(parts).lower()
    parts = [
        str(getattr(chunk, "text", "") or ""),
        str(getattr(chunk, "citation", "") or ""),
        str(getattr(chunk, "document_id", "") or ""),
        str(getattr(chunk, "title", "") or ""),
        json.dumps(getattr(chunk, "metadata", {}) or {}, ensure_ascii=False),
    ]
    return "\n".join(parts).lower()


def _text_blob(packed: dict[str, Any]) -> str:
    parts = [str(packed.get("answer_context") or packed.get("context") or "")]
    for c in packed.get("chunks") or []:
        parts.append(_chunk_blob(c))
    for cite in packed.get("citations") or []:
        if isinstance(cite, dict):
            parts.append(str(cite.get("citation") or ""))
            parts.append(str(cite.get("document_id") or ""))
        else:
            parts.append(str(cite))
    return "\n".join(parts).lower()


def _first_relevant_rank(chunks: list[Any], expect_any: list[str]) -> tuple[int | None, list[str]]:
    """返回 1-based 首个命中 rank；无命中则 None。"""
    if not expect_any:
        return (1 if chunks else None), []
    for i, ch in enumerate(chunks, start=1):
        blob = _chunk_blob(ch)
        hit_terms = [t for t in expect_any if t and t in blob]
        if hit_terms:
            return i, sorted(set(hit_terms))
    return None, []


def _is_relevant_chunk(chunk: Any, expect_any: list[str]) -> bool:
    """chunk 是否相关：blob 命中任意 expect_any（与 Hit 判定一致）。"""
    if not expect_any:
        return True
    blob = _chunk_blob(chunk)
    return any(t and t in blob for t in expect_any)


def _precision_at_k(chunks: list[Any], expect_any: list[str], k: int) -> float:
    """Precision@K = top-K 中相关 chunk 数 / K。空检索返回 0。"""
    if k <= 0:
        return 0.0
    top = list(chunks)[:k]
    if not top:
        return 0.0
    relevant = sum(1 for ch in top if _is_relevant_chunk(ch, expect_any))
    return relevant / float(k)


def _term_recall_at_k(chunks: list[Any], expect_any: list[str], k: int) -> float:
    """TermRecall@K = top-K 覆盖的 expect_any 词数 / |expect_any|。

    expect_any 为空时：有结果记 1.0，无结果记 0.0。
    """
    top = list(chunks)[:k]
    if not expect_any:
        return 1.0 if top else 0.0
    if not top:
        return 0.0
    blob = "\n".join(_chunk_blob(ch) for ch in top)
    hit = sum(1 for t in expect_any if t and t in blob)
    return hit / float(len(expect_any))


def _chunk_id_of(chunk: Any) -> str:
    if isinstance(chunk, dict):
        return str(chunk.get("chunk_id") or "")
    return str(getattr(chunk, "chunk_id", "") or "")


def _document_id_of(chunk: Any) -> str:
    if isinstance(chunk, dict):
        return str(chunk.get("document_id") or "")
    return str(getattr(chunk, "document_id", "") or "")


def _anchor_hit_at_k(chunks: list[Any], case: dict[str, Any], k: int) -> dict[str, float | None]:
    """有源标注时的锚点召回（0/1）；缺标注字段时对应值为 None。"""
    top = list(chunks)[:k]
    src_chunk = str(case.get("source_chunk_id") or "").strip()
    src_doc = str(case.get("source_document_id") or "").strip()
    out: dict[str, float | None] = {"chunk": None, "doc": None}
    if src_chunk:
        out["chunk"] = 1.0 if any(_chunk_id_of(ch) == src_chunk for ch in top) else 0.0
    if src_doc:
        out["doc"] = 1.0 if any(_document_id_of(ch) == src_doc for ch in top) else 0.0
    return out


def _graded_relevance(case: dict[str, Any], expect_any: list[str]) -> list[tuple[str, int]]:
    """提取分级 relevance：(关键词小写, 等级)。向后兼容：无 relevance 字段时由 expect_any 退化为二元。"""
    rel = case.get("relevance")
    out: list[tuple[str, int]] = []
    if isinstance(rel, dict):
        out = [(str(k).lower(), max(0, int(v))) for k, v in rel.items()]
    elif isinstance(rel, list):
        for item in rel:
            if isinstance(item, dict):
                term = str(item.get("match") or "").lower()
                if term:
                    out.append((term, max(0, int(item.get("grade") or 1))))
    out = [(t, g) for t, g in out if t]
    if not out:
        out = [(t, 1) for t in expect_any if t]
    return out


def _chunk_gain(chunk: Any, graded: list[tuple[str, int]]) -> int:
    """某 chunk 的相关等级：命中的关键词中取最高 grade，未命中为 0。"""
    blob = _chunk_blob(chunk)
    gains = [g for t, g in graded if t and t in blob]
    return max(gains) if gains else 0


def _dcg(gains: list[int], k: int) -> float:
    import math

    total = 0.0
    for i, gain in enumerate(gains[:k], start=1):
        total += gain / math.log2(i + 1)
    return total


def ndcg_at_k(chunks: list[Any], graded: list[tuple[str, int]], k: int) -> float:
    """nDCG@k：按检索顺序的实际 DCG / 理想排序 DCG。无相关标注时返回 0。"""
    if not graded:
        return 0.0
    actual = [_chunk_gain(ch, graded) for ch in chunks]
    ideal = sorted((g for _, g in graded), reverse=True)
    idcg = _dcg(ideal, k)
    if idcg <= 0:
        return 0.0
    return _dcg(actual, k) / idcg


async def _eval_one(
    case: dict[str, Any],
    *,
    top_k: int,
    k_list: list[int],
) -> CaseResult:
    cid = str(case.get("id") or case.get("query") or "case")
    query = str(case.get("query") or "").strip()
    graded = _graded_relevance(
        case, [str(x).lower() for x in (case.get("expect_any") or [])]
    )
    expect_any = sorted({t for t, _ in graded})
    t0 = time.perf_counter()
    try:
        # 与 @K 对齐：勿被默认 rag_rerank_top_k=4 截断导致 Precision@5/TermRecall@5 虚低
        chunks = await hybrid_retrieve(
            query,
            top_k=top_k,
            rerank_top_k=max(k_list) if k_list else top_k,
        )
        packed = build_context(chunks)
        latency = (time.perf_counter() - t0) * 1000
        rank, matched = _first_relevant_rank(list(chunks), expect_any)
        context_fallback = False
        if rank is None and expect_any:
            # 回退：整包 context 命中只单独计数，不计入 hit_rate / Hit@K / MRR
            # （迭代 3 前会记 hit 但不计 rank，口径不诚实；现拆分为独立指标）
            blob = _text_blob(packed)
            matched = [t for t in expect_any if t and t in blob]
            if matched:
                context_fallback = True
        hit_map = {f"hit@{k}": bool(rank is not None and rank <= k) for k in k_list}
        ndcg_map = {f"ndcg@{k}": round(ndcg_at_k(list(chunks), graded, k), 4) for k in k_list}
        precision_map = {
            f"precision@{k}": round(_precision_at_k(list(chunks), expect_any, k), 4) for k in k_list
        }
        term_recall_map = {
            f"term_recall@{k}": round(_term_recall_at_k(list(chunks), expect_any, k), 4)
            for k in k_list
        }
        anchor_chunk_map: dict[str, float] | None = None
        anchor_doc_map: dict[str, float] | None = None
        for k in k_list:
            anchors = _anchor_hit_at_k(list(chunks), case, k)
            if anchors["chunk"] is not None:
                if anchor_chunk_map is None:
                    anchor_chunk_map = {}
                anchor_chunk_map[f"anchor_chunk@{k}"] = float(anchors["chunk"])
            if anchors["doc"] is not None:
                if anchor_doc_map is None:
                    anchor_doc_map = {}
                anchor_doc_map[f"anchor_doc@{k}"] = float(anchors["doc"])
        citations: list[str] = []
        for c in packed.get("citations") or []:
            if isinstance(c, dict):
                citations.append(str(c.get("citation") or c))
            else:
                citations.append(str(c))
        for c in packed.get("chunks") or []:
            if isinstance(c, dict) and c.get("citation"):
                citations.append(str(c["citation"]))
        if expect_any:
            # 严格口径：只有进入检索榜单的命中才算 hit
            hit = bool(rank is not None)
        else:
            hit = bool(chunks)
        rr = (1.0 / rank) if rank else 0.0
        return CaseResult(
            id=cid,
            query=query,
            hit=hit,
            hit_at_k=hit_map,
            first_relevant_rank=rank,
            reciprocal_rank=rr,
            citation_present=bool(citations),
            no_answer=bool(packed.get("no_answer")),
            latency_ms=latency,
            matched_terms=matched,
            citations=citations[:8],
            context_fallback_hit=context_fallback,
            ndcg_at_k=ndcg_map,
            precision_at_k=precision_map,
            term_recall_at_k=term_recall_map,
            anchor_chunk_at_k=anchor_chunk_map,
            anchor_doc_at_k=anchor_doc_map,
        )
    except Exception as exc:  # noqa: BLE001 — 评估容错
        latency = (time.perf_counter() - t0) * 1000
        return CaseResult(
            id=cid,
            query=query,
            hit=False,
            hit_at_k={f"hit@{k}": False for k in k_list},
            ndcg_at_k={f"ndcg@{k}": 0.0 for k in k_list},
            precision_at_k={f"precision@{k}": 0.0 for k in k_list},
            term_recall_at_k={f"term_recall@{k}": 0.0 for k in k_list},
            latency_ms=latency,
            error=str(exc),
        )


def run_rag_eval(
    *,
    suite_path: Path,
    top_k: int = 4,
    out_path: Path | None = None,
    md_path: Path | None = None,
    min_hit_rate: float | None = None,
    config_path: Path | None = None,
) -> EvalReport:
    suite = _load_suite(suite_path)
    cfg = load_eval_config(config_path)
    params = cfg.get("parameters") if isinstance(cfg.get("parameters"), dict) else {}
    thresholds_cfg = cfg.get("thresholds") if isinstance(cfg.get("thresholds"), dict) else {}
    retrieval_th = (
        thresholds_cfg.get("retrieval") if isinstance(thresholds_cfg.get("retrieval"), dict) else {}
    )

    cases_raw = list(suite.get("cases") or [])
    limit = params.get("dataset_limit")
    if isinstance(limit, int) and limit > 0:
        cases_raw = cases_raw[:limit]

    k_list = list(params.get("top_k_list") or [1, 3, 5])
    k_list = sorted({int(k) for k in k_list if int(k) > 0})
    if not k_list:
        k_list = [1, 3, 5]
    # 检索至少拿 max(K, top_k)
    retrieve_k = max(top_k, max(k_list))

    threshold = float(
        min_hit_rate
        if min_hit_rate is not None
        else suite.get("min_hit_rate", retrieval_th.get("hit_rate", 0.5))
    )
    min_mrr = float(retrieval_th.get("mrr", 0.0) or 0.0)

    async def _run() -> list[CaseResult]:
        out: list[CaseResult] = []
        for c in track_cases(cases_raw, desc="retrieval"):
            out.append(await _eval_one(c, top_k=retrieve_k, k_list=k_list))
        return out

    results = asyncio.run(_run())
    n = len(results) or 1
    hit_rate = sum(1 for c in results if c.hit) / n
    citation_rate = sum(1 for c in results if c.citation_present) / n
    avg_latency = sum(c.latency_ms for c in results) / n
    mrr = sum(c.reciprocal_rank for c in results) / n
    fallback_hits = sum(1 for c in results if c.context_fallback_hit)
    hit_at_k = {
        f"hit@{k}": sum(1 for c in results if c.hit_at_k.get(f"hit@{k}")) / n for k in k_list
    }
    ndcg_k = {
        f"ndcg@{k}": sum(c.ndcg_at_k.get(f"ndcg@{k}", 0.0) for c in results) / n
        for k in k_list
    }
    precision_k = {
        f"precision@{k}": sum(c.precision_at_k.get(f"precision@{k}", 0.0) for c in results) / n
        for k in k_list
    }
    term_recall_k = {
        f"term_recall@{k}": sum(c.term_recall_at_k.get(f"term_recall@{k}", 0.0) for c in results)
        / n
        for k in k_list
    }
    anchor_chunk_cases = [c for c in results if c.anchor_chunk_at_k]
    anchor_doc_cases = [c for c in results if c.anchor_doc_at_k]
    n_ac = len(anchor_chunk_cases) or 1
    n_ad = len(anchor_doc_cases) or 1
    anchor_chunk_k = {
        f"anchor_chunk@{k}": (
            sum(c.anchor_chunk_at_k.get(f"anchor_chunk@{k}", 0.0) for c in anchor_chunk_cases) / n_ac
            if anchor_chunk_cases
            else 0.0
        )
        for k in k_list
    }
    anchor_doc_k = {
        f"anchor_doc@{k}": (
            sum(c.anchor_doc_at_k.get(f"anchor_doc@{k}", 0.0) for c in anchor_doc_cases) / n_ad
            if anchor_doc_cases
            else 0.0
        )
        for k in k_list
    }

    ok = hit_rate >= threshold
    if min_mrr > 0:
        ok = ok and mrr >= min_mrr
    min_ndcg = float(retrieval_th.get("ndcg", 0.0) or 0.0)
    if min_ndcg > 0:
        ok = ok and ndcg_k.get(f"ndcg@{max(k_list)}", 0.0) >= min_ndcg
    for k in k_list:
        key = f"recall@{k}"
        if key in retrieval_th:
            ok = ok and hit_at_k.get(f"hit@{k}", 0.0) >= float(retrieval_th[key])
    min_precision_at_5 = float(retrieval_th.get("precision_at_5", 0.0) or 0.0)
    if min_precision_at_5 > 0:
        ok = ok and precision_k.get("precision@5", 0.0) >= min_precision_at_5
    min_term_recall_at_5 = float(retrieval_th.get("term_recall_at_5", 0.0) or 0.0)
    if min_term_recall_at_5 > 0:
        ok = ok and term_recall_k.get("term_recall@5", 0.0) >= min_term_recall_at_5

    report = EvalReport(
        suite=str(suite_path),
        cases=results,
        hit_rate=hit_rate,
        citation_rate=citation_rate,
        avg_latency_ms=avg_latency,
        hit_at_k=hit_at_k,
        ndcg_at_k=ndcg_k,
        precision_at_k=precision_k,
        term_recall_at_k=term_recall_k,
        anchor_chunk_at_k=anchor_chunk_k if anchor_chunk_cases else {},
        anchor_doc_at_k=anchor_doc_k if anchor_doc_cases else {},
        anchor_chunk_cases=len(anchor_chunk_cases),
        anchor_doc_cases=len(anchor_doc_cases),
        fallback_hits=fallback_hits,
        mrr=mrr,
        ok=ok,
        thresholds={
            "min_hit_rate": threshold,
            "min_mrr": min_mrr,
            "min_ndcg": min_ndcg,
            "min_precision_at_5": min_precision_at_5,
            "min_term_recall_at_5": min_term_recall_at_5,
            "retrieval": retrieval_th,
        },
    )

    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if md_path:
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(report.to_markdown(), encoding="utf-8")
    elif out_path:
        # 默认同目录写一份 md
        sibling = out_path.with_suffix(".md")
        sibling.write_text(report.to_markdown(), encoding="utf-8")

    return report
