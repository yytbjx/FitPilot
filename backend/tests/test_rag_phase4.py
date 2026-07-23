"""分块策略 / Query Understanding / Citation / 生命周期。"""

from __future__ import annotations

from app.rag import RetrievedChunk
from app.rag.chunk_strategies import (
    compare_chunk_strategies,
    detect_doc_type,
    split_with_strategy,
    strategy_for_doc_type,
)
from app.rag.citations import citation_coverage, map_citations
from app.rag.query_understanding import analyze_query, classify_query_type, extract_entities
from app.rag.retrieval_plan import build_retrieval_plan


def test_detect_safety_and_faq():
    assert detect_doc_type(path="knowledge_base/raw/safety_boundary.md", title="边界", text="禁止诊断") == "safety"
    assert detect_doc_type(path="x/faq.md", title="FAQ", text="Q: 蛋白？\nA: 1.6") == "faq"
    assert strategy_for_doc_type("guide") == "parent_child"


def test_split_strategies_produce_chunks():
    text = "# 蛋白\n\n每日 1.6-2.2g/kg。\n\n# 热量\n\n保持缺口。"
    for strategy in ("fixed", "heading", "faq_qa", "clause"):
        chunks = split_with_strategy(
            text,
            document_id="d",
            version_id="v1",
            title="t",
            strategy=strategy,  # type: ignore[arg-type]
        )
        assert chunks
        assert all(c.metadata.get("chunk_strategy") == strategy for c in chunks)


def test_compare_chunk_strategies_report():
    report = compare_chunk_strategies(
        "# 减脂 FAQ\n\n## 缺口\n\n300kcal\n\n## 蛋白\n\n1.6g",
        title="减脂 FAQ",
        source_path="faq.md",
    )
    assert report["detected_doc_type"] == "faq"
    assert "heading" in report["strategies"]
    assert report["recommended_strategy"] == "faq_qa"


def test_query_understanding_structured():
    info = analyze_query("为什么减脂期要保证蛋白质并且控制热量")
    assert info["query_type"] == "why"
    assert "protein" in info["entities"] or "fat_loss" in info["entities"]
    assert info["use_multi_query"] is True
    assert classify_query_type("胸痛还能训练吗") == "risk"
    assert extract_entities("深蹲动作要领") == ["squat"]


def test_retrieval_plan_uses_query_type():
    plan = build_retrieval_plan("胸痛还能练吗")
    assert plan.strategy == "high_risk"
    assert plan.query_understanding.get("query_type") == "risk"
    fact = build_retrieval_plan("什么是蛋白质")
    assert fact.strategy in {"simple_fact", "default", "complex_explain"}


def test_citation_mapping_and_coverage():
    chunks = [
        RetrievedChunk(
            chunk_id="c1",
            text="蛋白建议 1.6-2.2",
            score=0.9,
            title="蛋白",
            section_path="营养/蛋白",
            document_id="d1",
            version_id="v1",
            citation="d1#1",
            metadata={"authority_level": 2, "doc_type": "guide"},
        ),
        RetrievedChunk(
            chunk_id="c2",
            text="热量缺口",
            score=0.5,
            title="热量",
            document_id="d2",
            version_id="v1",
            citation="d2#1",
        ),
    ]
    cites = map_citations(chunks, answer_text="根据证据 [1] 建议保证蛋白。", index_version="idx_test")
    assert cites[0]["heading_path"] == ["营养", "蛋白"]
    assert cites[0]["cited_in_answer"] is True
    assert cites[1]["cited_in_answer"] is False
    assert cites[0]["index_version"] == "idx_test"
    cov = citation_coverage(cites)
    assert cov["cited_count"] == 1
    assert cov["coverage"] == 0.5


def test_uow_has_users_repo():
    class _S:
        async def commit(self):
            return None

        async def rollback(self):
            return None

    from app.infrastructure.persistence.uow import SqlAlchemyUnitOfWork

    uow = SqlAlchemyUnitOfWork(_S())  # type: ignore[arg-type]
    assert uow.users is not None
