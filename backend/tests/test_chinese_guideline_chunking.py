"""中文章节规范化切块单测。"""

from app.rag.chunking import normalize_plain_chinese_sections, split_text
from app.rag.chunk_strategies import detect_doc_type


def test_normalize_chinese_guidelines_sections():
    text = "准则一 食物多样，合理搭配\n\n坚持谷类为主。\n\n准则二 吃动平衡，健康体重\n\n每周至少150分钟。"
    normalized = normalize_plain_chinese_sections(text)
    assert "## 准则一" in normalized
    assert "## 准则二" in normalized
    chunks = split_text(
        text,
        document_id="cn_diet",
        version_id="v1",
        title="膳食指南",
        source_path="knowledge_base/raw/curated/guidelines/x.md",
    )
    assert len(chunks) >= 2
    assert any("准则一" in (c.section_path or "") for c in chunks)


def test_detect_guidelines_path_as_guide():
    assert (
        detect_doc_type(
            path="knowledge_base/raw/curated/guidelines/who_x.md",
            title="身体活动",
            text="成年人每周150分钟",
            parse_format="md",
        )
        == "guide"
    )
