"""评估辅助函数单测（不依赖 Qdrant）。"""

import re
from pathlib import Path

from app.eval.rag_eval import (
    _anchor_hit_at_k,
    _first_relevant_rank,
    _precision_at_k,
    _term_recall_at_k,
    load_eval_config,
)


def test_first_relevant_rank():
    chunks = [
        {"text": "无关内容", "document_id": "a"},
        {"text": "减脂期蛋白质建议 1.6-2.2", "document_id": "b"},
    ]
    rank, matched = _first_relevant_rank(chunks, ["蛋白", "1.6"])
    assert rank == 2
    assert matched


def test_precision_and_term_recall_at_k():
    chunks = [
        {"text": "蛋白质 1.6", "chunk_id": "c1", "document_id": "d1"},
        {"text": "无关内容", "chunk_id": "c2", "document_id": "d2"},
        {"text": "2.2 g/kg", "chunk_id": "c3", "document_id": "d1"},
    ]
    expect = ["蛋白", "1.6", "2.2"]
    # K=3：相关 2/3
    p3 = _precision_at_k(chunks, expect, 3)
    assert abs(p3 - 2 / 3) < 1e-6
    # Hit@3=1 ⇒ Precision@3 >= 1/3
    assert p3 >= 1 / 3
    # TermRecall@3：三个词都在 top-3 出现 → 1.0
    assert abs(_term_recall_at_k(chunks, expect, 3) - 1.0) < 1e-6
    # TermRecall@1：仅覆盖 蛋白、1.6 → 2/3
    assert abs(_term_recall_at_k(chunks, expect, 1) - 2 / 3) < 1e-6
    # 无命中
    assert _precision_at_k([{"text": "xxx"}], expect, 1) == 0.0
    assert _term_recall_at_k([{"text": "xxx"}], expect, 1) == 0.0
    # expect 为空：有结果=1，无结果=0
    assert _term_recall_at_k(chunks, [], 3) == 1.0
    assert _term_recall_at_k([], [], 3) == 0.0


def test_anchor_hit_at_k():
    chunks = [
        {"text": "a", "chunk_id": "c1", "document_id": "docA"},
        {"text": "b", "chunk_id": "c2", "document_id": "docB"},
    ]
    case = {"source_chunk_id": "c2", "source_document_id": "docB"}
    a1 = _anchor_hit_at_k(chunks, case, 1)
    assert a1["chunk"] == 0.0
    assert a1["doc"] == 0.0
    a2 = _anchor_hit_at_k(chunks, case, 2)
    assert a2["chunk"] == 1.0
    assert a2["doc"] == 1.0
    # 无源字段
    empty = _anchor_hit_at_k(chunks, {}, 2)
    assert empty["chunk"] is None and empty["doc"] is None


def test_load_eval_config_yaml():
    cfg = load_eval_config(Path(__file__).resolve().parents[2] / "evals" / "eval_config.yaml")
    assert "parameters" in cfg
    assert 1 in cfg["parameters"]["top_k_list"] or cfg["parameters"]["top_k_list"][0] == 1
    th = cfg["thresholds"]["retrieval"]
    assert "precision_at_5" in th
    assert "term_recall_at_5" in th


def test_diversify_by_document():
    from app.rag import RetrievedChunk
    from app.rag.retrieve import diversify_by_document

    chunks = [
        RetrievedChunk(chunk_id="1", text="a", score=3.0, document_id="d1"),
        RetrievedChunk(chunk_id="2", text="b", score=2.0, document_id="d1"),
        RetrievedChunk(chunk_id="3", text="c", score=1.0, document_id="d2"),
        RetrievedChunk(chunk_id="4", text="d", score=0.5, document_id="d3"),
    ]
    out = diversify_by_document(chunks, limit=3, max_per_doc=1)
    assert [c.chunk_id for c in out] == ["1", "3", "4"]
    out2 = diversify_by_document(chunks, limit=3, max_per_doc=0)
    assert [c.chunk_id for c in out2] == ["1", "2", "3"]


def test_suite_generator_expect_and_strip():
    import importlib.util
    import random
    from pathlib import Path

    mod_path = Path(__file__).resolve().parents[2] / "scripts" / "generate_rag_suite_from_kb.py"
    spec = importlib.util.spec_from_file_location("generate_rag_suite_from_kb", mod_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    text = "成年人每周应进行至少 150 分钟中等强度身体活动，并减少久坐。"
    expect = mod.pick_expect_any(
        theme="who_pa", text=text, document_id="who_pa_guide", rng=random.Random(1)
    )
    assert 2 <= len(expect) <= 3
    assert all(t in text for t in expect)
    assert not any(re.fullmatch(r"\d{5,}", t or "") for t in expect)
    assert "who" not in expect  # 禁止仅 document_id slug

    # 半截替换应被拒绝：嵌在更长词中的短 expect 不剥
    q = "优质蛋白质可以从哪些食物获取？"
    stripped = mod.strip_expect_from_query(q, ["蛋白"], keep_terms=[])
    assert stripped == q  # 「蛋白」嵌在「蛋白质」中间，不替换
    ok = mod.strip_expect_from_query(
        "力量训练新手每周练几次比较合适？", ["力量训练"], keep_terms=[]
    )
    assert "该主题" in ok
    assert mod.query_is_acceptable(ok)
    assert not mod.query_is_acceptable("优质相关内容质怎么获取？")
    assert not mod.query_is_acceptable("短")
