"""离线确定性 RAG 检索门禁：无 Qdrant / Ollama / Embedding 模型依赖。

设计：
- 复用真实 RAG 代码路径：chunking.split_text 切分、BM25Index 稀疏检索、
  rrf_fuse 融合、build_context（内含 Evidence Gate）拒答判定；
- dense 侧用确定性哈希向量（token 投影 + L2 归一化）代替 bge 模型嵌入，
  内存 dict 代替 Qdrant —— 同一输入永远得到同一结果，满足 CI 确定性；
- dense 结果加余弦相似度下限，模拟真实向量库对无关查询的低分过滤，
  否则哈希 dense 会对任意查询返回全库，no_answer 层永远无法拒答。

语料：evals/rag_fixture/*.md（小型固定语料，内容摘自 knowledge_base/raw 真实文档）。
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.eval.rag_eval import _first_relevant_rank, _graded_relevance, ndcg_at_k
from app.rag import DocumentChunk, RetrievedChunk
from app.rag.bm25 import BM25Index, tokenize
from app.rag.chunking import split_text
from app.rag.context import build_context
from app.rag.retrieve import rrf_fuse

_HASH_DIM = 128
# 哈希 dense 的余弦下限：无关查询的随机余弦一般 < 0.15，相关查询与目标 chunk 通常 > 0.3
_DENSE_MIN_COSINE = 0.2
# 离线语义下限：候选 chunk 的查询词覆盖率（命中的查询 token 占比）。
# 模拟真实管线中 dense 相似度对无关查询的过滤——单字切词下无关查询会对全库产生
# 低分 BM25 命中，没有该下限时 no_answer 层永远无法拒答。实测：fixture 可答案例
# 目标 chunk 覆盖率 ≥ 0.44，无关案例 ≤ 0.30。
_MIN_QUERY_COVERAGE = 0.35


def _hash_embed(text: str) -> list[float]:
    """确定性伪嵌入：token 哈希投影到固定维度后 L2 归一化。"""
    vec = [0.0] * _HASH_DIM
    for tok in tokenize(text):
        h = int(hashlib.sha1(tok.encode("utf-8")).hexdigest(), 16)
        vec[h % _HASH_DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class OfflineIndex:
    """内存混合索引：BM25（真实路径）+ 哈希 dense（确定性 dummy）。"""

    def __init__(self, chunks: list[DocumentChunk]) -> None:
        self.chunks = chunks
        self.bm25 = BM25Index()
        self.bm25.build((c.chunk_id, c.text, c.to_payload()) for c in chunks)
        self.vectors = {c.chunk_id: _hash_embed(c.text) for c in chunks}
        self.payloads = {c.chunk_id: c.to_payload() for c in chunks}

    @classmethod
    def from_fixture_dir(cls, fixture_dir: Path) -> "OfflineIndex":
        chunks: list[DocumentChunk] = []
        for path in sorted(fixture_dir.glob("*.md")):
            chunks.extend(
                split_text(
                    path.read_text(encoding="utf-8"),
                    document_id=path.stem,
                    version_id="offline",
                    title=path.stem,
                    source_path=str(path),
                )
            )
        if not chunks:
            raise ValueError(f"离线 fixture 语料为空：{fixture_dir}")
        return cls(chunks)

    def retrieve(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        qv = _hash_embed(query)
        query_tokens = set(tokenize(query))
        dense = [
            (cid, _cosine(qv, vec)) for cid, vec in self.vectors.items()
        ]
        dense = [d for d in dense if d[1] >= _DENSE_MIN_COSINE]
        dense.sort(key=lambda x: x[1], reverse=True)
        dense = dense[:top_k]
        sparse = self.bm25.search(query, top_k=top_k)
        fused = rrf_fuse(
            [[(d[0], d[1]) for d in dense], [(s[0], s[1]) for s in sparse]]
        )
        out: list[RetrievedChunk] = []
        for cid, score in fused[: top_k * 2]:
            p = self.payloads.get(cid) or {}
            text = str(p.get("text") or "")
            if not text.strip():
                continue
            if query_tokens:
                doc_tokens = set(tokenize(text))
                coverage = len(query_tokens & doc_tokens) / len(query_tokens)
                if coverage < _MIN_QUERY_COVERAGE:
                    continue
            out.append(
                RetrievedChunk(
                    chunk_id=cid,
                    text=text,
                    score=float(score),
                    title=str(p.get("title") or ""),
                    section_path=str(p.get("section_path") or ""),
                    source_path=str(p.get("source_path") or ""),
                    document_id=str(p.get("document_id") or ""),
                    version_id=str(p.get("version_id") or ""),
                    citation=f"{p.get('title') or p.get('document_id')}#offline@offline",
                    metadata={"retrieval_source": "dense+bm25"},
                )
            )
            if len(out) >= top_k:
                break
        return out


@dataclass
class OfflineRagEvalResult:
    """离线检索 + 拒答双层结果。"""

    total: int = 0
    retrieval_cases: int = 0
    retrieval_hits: int = 0
    mrr: float = 0.0
    hit_at_k: dict[str, float] = field(default_factory=dict)
    ndcg_at_k: dict[str, float] = field(default_factory=dict)
    no_answer_total: int = 0
    true_positive: int = 0
    false_positive: int = 0
    false_negative: int = 0
    cases: list[dict[str, Any]] = field(default_factory=list)
    label: str = "Offline RAG Eval"

    @property
    def hit_rate(self) -> float:
        return self.retrieval_hits / self.retrieval_cases if self.retrieval_cases else 0.0

    @property
    def no_answer_recall(self) -> float:
        denom = self.true_positive + self.false_negative
        return self.true_positive / denom if denom else 0.0

    @property
    def no_answer_precision(self) -> float:
        denom = self.true_positive + self.false_positive
        return self.true_positive / denom if denom else 0.0

    def summary_text(self) -> str:
        return (
            f"{self.label}: retrieval hit_rate={self.hit_rate:.2%} mrr={self.mrr:.4f} | "
            f"no_answer recall={self.no_answer_recall:.2%} precision={self.no_answer_precision:.2%}"
        )


def run_offline_rag_eval(
    fixture_dir: Path,
    suite_path: Path,
    *,
    top_k: int = 5,
    k_list: list[int] | None = None,
) -> OfflineRagEvalResult:
    """跑离线检索 + 拒答评测。确定性：同语料同套件结果完全一致。"""
    import json

    k_list = sorted(set(k_list or [1, 3, 5]))
    index = OfflineIndex.from_fixture_dir(fixture_dir)
    raw = json.loads(suite_path.read_text(encoding="utf-8"))
    result = OfflineRagEvalResult()

    rr_sum = 0.0
    hit_at_k_count = {k: 0 for k in k_list}
    ndcg_sum = {k: 0.0 for k in k_list}

    for case in raw.get("cases") or []:
        result.total += 1
        query = str(case.get("query") or "").strip()
        expect_no_answer = bool(case.get("expect_no_answer", False))
        chunks = index.retrieve(query, top_k=max(top_k, max(k_list)))
        packed = build_context(chunks)
        got_no_answer = bool(packed.get("no_answer"))
        record: dict[str, Any] = {
            "id": case.get("id"),
            "query": query,
            "expect_no_answer": expect_no_answer,
            "got_no_answer": got_no_answer,
        }

        if expect_no_answer:
            result.no_answer_total += 1
            if got_no_answer:
                result.true_positive += 1
            else:
                result.false_negative += 1
            record["correct"] = got_no_answer
            result.cases.append(record)
            continue

        # 可答案例：拒答则计入 no_answer 误判（FP），检索指标照算
        result.no_answer_total += 1
        if got_no_answer:
            result.false_positive += 1
        graded = _graded_relevance(
            case, [str(x).lower() for x in (case.get("expect_any") or [])]
        )
        expect_any = sorted({t for t, _ in graded})
        rank, matched = _first_relevant_rank(list(chunks), expect_any)
        result.retrieval_cases += 1
        if rank is not None:
            result.retrieval_hits += 1
            rr_sum += 1.0 / rank
        for k in k_list:
            if rank is not None and rank <= k:
                hit_at_k_count[k] += 1
            ndcg_sum[k] += ndcg_at_k(list(chunks), graded, k)
        record.update(
            {
                "rank": rank,
                "matched_terms": matched,
                "hit": rank is not None,
            }
        )
        result.cases.append(record)

    n = result.retrieval_cases or 1
    result.mrr = rr_sum / n
    result.hit_at_k = {f"hit@{k}": hit_at_k_count[k] / n for k in k_list}
    result.ndcg_at_k = {f"ndcg@{k}": round(ndcg_sum[k] / n, 4) for k in k_list}
    return result
