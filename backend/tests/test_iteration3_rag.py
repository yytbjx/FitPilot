"""迭代 3 测试：删除传播 / nDCG / 动态维度 / 索引版本指纹 / Evidence Gate 收敛 / 离线检索门禁。"""

from pathlib import Path
from types import SimpleNamespace

import app.rag.ingest as ingest_mod
import app.rag.knowledge_lifecycle as kl
from app.eval.offline_rag_eval import run_offline_rag_eval
from app.eval.rag_eval import _graded_relevance, ndcg_at_k
from app.rag import RetrievedChunk
from app.rag.context import build_context
from app.rag.embeddings import embedding_dim
from app.rag.evidence_gate import assess_evidence, score_scale_of

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------- 任务 17：删除传播 ----------

class _StubQdrant:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, str]] = []

    def delete_by_payload(self, field: str, value: str) -> None:
        self.deleted.append((field, value))


def test_delete_document_propagates(monkeypatch):
    """delete_document 应同时清理 Qdrant（按 document_id）与 BM25 条目并持久化。"""
    from app.rag.bm25 import BM25Index

    idx = BM25Index()
    idx.build(
        [
            ("d1_0_aa", "蛋白质摄入建议", {"document_id": "d1", "text": "蛋白质摄入建议"}),
            ("d1_1_bb", "力量训练基础", {"document_id": "d1", "text": "力量训练基础"}),
            ("d2_0_cc", "胸痛立即就医", {"document_id": "d2", "text": "胸痛立即就医"}),
        ]
    )
    stub = _StubQdrant()
    persisted: list[BM25Index] = []
    monkeypatch.setattr(ingest_mod, "get_qdrant_service", lambda: stub)
    monkeypatch.setattr(ingest_mod, "get_bm25_index", lambda: idx)
    monkeypatch.setattr(ingest_mod, "persist_bm25", lambda new_idx: persisted.append(new_idx))

    result = ingest_mod.delete_document("d1")

    assert stub.deleted == [("document_id", "d1")]
    assert result["bm25_removed"] == 2
    assert result["qdrant_purged"] is True
    assert persisted, "应持久化 bm25_index.json"
    remaining = {p.get("document_id") for p in persisted[0].payloads.values()}
    assert remaining == {"d2"}


# ---------- 任务 19：nDCG@k ----------

def test_ndcg_perfect_and_reversed():
    chunks_perfect = [
        {"text": "蛋白质 1.6-2.2 g/kg 核心答案", "document_id": "a"},
        {"text": "蛋白相关背景", "document_id": "b"},
        {"text": "完全无关的内容", "document_id": "c"},
    ]
    graded = [("1.6", 2), ("蛋白", 1)]
    assert ndcg_at_k(chunks_perfect, graded, 3) == 1.0
    chunks_reversed = list(reversed(chunks_perfect))
    score = ndcg_at_k(chunks_reversed, graded, 3)
    assert 0.0 < score < 1.0


def test_graded_relevance_backward_compat():
    """无 relevance 字段时由 expect_any 退化为二元（grade=1）。"""
    case = {"expect_any": ["蛋白", "1.6"]}
    graded = _graded_relevance(case, ["蛋白", "1.6"])
    assert sorted(graded) == [("1.6", 1), ("蛋白", 1)]
    case2 = {"relevance": {"1.6": 2, "蛋白": 1}}
    graded2 = _graded_relevance(case2, [])
    assert ("1.6", 2) in graded2 and ("蛋白", 1) in graded2


# ---------- 任务 18：动态维度 ----------

class _FakeModel:
    def get_sentence_embedding_dimension(self) -> int:
        return 384


def test_embedding_dim_dynamic(monkeypatch):
    """embedding_dim 从已加载模型动态获取，不再硬编码 512。"""
    import app.rag.embeddings as emb

    embedding_dim.cache_clear()
    monkeypatch.setattr(emb, "get_embedding_model", lambda: _FakeModel())
    monkeypatch.setattr(
        emb, "get_settings", lambda: SimpleNamespace(embedding_dim_override=None)
    )
    assert embedding_dim() == 384
    embedding_dim.cache_clear()


def test_embedding_dim_override(monkeypatch):
    """配置覆盖优先，不触发模型加载。"""
    import app.rag.embeddings as emb

    embedding_dim.cache_clear()
    monkeypatch.setattr(
        emb, "get_settings", lambda: SimpleNamespace(embedding_dim_override=768)
    )
    monkeypatch.setattr(
        emb,
        "get_embedding_model",
        lambda: (_ for _ in ()).throw(AssertionError("不应加载模型")),
    )
    assert embedding_dim() == 768
    embedding_dim.cache_clear()


# ---------- 任务 18：索引版本指纹 ----------

def test_index_version_signature_mismatch(monkeypatch):
    """active 版本指纹与当前配置不匹配时 compatible=False（提示 re-ingest）。"""
    monkeypatch.setattr(kl, "embedding_dim", lambda: 512)
    sig = kl.current_index_signature()
    assert sig["index_signature"]
    assert sig["embedding_dim"] == 512
    assert sig["chunker_version"] == kl.CHUNKER_VERSION

    monkeypatch.setattr(
        kl,
        "get_active_index_version",
        lambda: {"index_version": "idx_old", "index_signature": "deadbeefcafe"},
    )
    compat = kl.check_active_version_compatible()
    assert compat["compatible"] is False

    monkeypatch.setattr(
        kl,
        "get_active_index_version",
        lambda: {
            "index_version": "idx_ok",
            "index_signature": sig["index_signature"],
        },
    )
    assert kl.check_active_version_compatible()["compatible"] is True


def test_index_version_signature_config_change(monkeypatch):
    """embedding 模型变化应改变指纹。"""
    monkeypatch.setattr(kl, "embedding_dim", lambda: 512)
    before = kl.current_index_signature()["index_signature"]
    monkeypatch.setattr(
        kl,
        "get_settings",
        lambda: SimpleNamespace(
            resolved_embedding_model="BAAI/bge-m3",
            rag_chunk_strategy="auto",
        ),
    )
    after = kl.current_index_signature()["index_signature"]
    assert before != after


# ---------- 任务 18：Evidence Gate 收敛 ----------

def _chunk(score: float, cid: str = "c1") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid,
        text="减脂期蛋白质摄入建议。",
        score=score,
        title="t",
        document_id="d1",
    )


def test_score_scale_detection():
    assert score_scale_of([0.0164, 0.0328]) == "rrf"
    assert score_scale_of([-3.0, 5.0]) == "rerank"
    assert score_scale_of([2.5, 1.0]) == "rerank"
    assert score_scale_of([]) == "unknown"


def test_conflict_skipped_for_rrf_scores():
    """RRF 分体系下不做极性冲突检测（迭代 3 前 (max-min)>5 永不触发，已显式跳过）。"""
    chunks = [_chunk(0.03, "a"), _chunk(0.001, "b")]
    a = assess_evidence(chunks)
    assert a.score_scale == "rrf"
    assert a.conflicts == []


def test_conflict_detected_for_rerank_scores():
    chunks = [_chunk(6.0, "a"), _chunk(-2.0, "b")]
    a = assess_evidence(chunks)
    assert a.score_scale == "rerank"
    assert "score_polarity_conflict" in a.conflicts
    assert a.answerable is False
    assert a.reason == "CONFLICTING_EVIDENCE"


def test_build_context_delegates_to_gate():
    """build_context 的拒答判定与 assess_evidence 一致（单套逻辑）。"""
    weak = [_chunk(-3.0, "a"), _chunk(-4.0, "b")]
    packed = build_context(weak)
    a = assess_evidence(weak)
    assert packed["no_answer"] is True
    assert a.answerable is False
    assert packed["reason_detail"] == a.reason == "LOW_CONFIDENCE"

    strong = [_chunk(5.0, "a"), _chunk(4.0, "b"), _chunk(3.5, "c"), _chunk(3.0, "d")]
    packed2 = build_context(strong)
    a2 = assess_evidence(strong)
    assert packed2["no_answer"] == (not a2.answerable)
    assert packed2["no_answer"] is False


# ---------- 任务 19：离线确定性检索门禁 ----------

def test_offline_rag_eval_deterministic_pass():
    """离线 fixture 检索 + 拒答应确定性通过门禁阈值（hit_rate>=0.7, mrr>=0.3, recall>=0.7, precision>=0.6）。"""
    r1 = run_offline_rag_eval(
        REPO_ROOT / "evals" / "rag_fixture", REPO_ROOT / "evals" / "golden_rag_offline.json"
    )
    r2 = run_offline_rag_eval(
        REPO_ROOT / "evals" / "rag_fixture", REPO_ROOT / "evals" / "golden_rag_offline.json"
    )
    assert r1.hit_rate == r2.hit_rate and r1.mrr == r2.mrr
    assert r1.hit_rate >= 0.7 and r1.mrr >= 0.3
    assert r1.no_answer_recall >= 0.7 and r1.no_answer_precision >= 0.6
    assert r1.retrieval_cases > 0 and r1.no_answer_total > 0
