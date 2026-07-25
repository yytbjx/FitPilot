"""BM25 / 切分基础测试。"""

from app.rag.bm25 import BM25Index, tokenize
from app.rag.chunking import split_text
from app.rag.context import build_context


def test_tokenize_chinese():
    toks = tokenize("蛋白质摄入与减脂")
    assert "蛋" in toks and "白" in toks


def test_bm25_search():
    idx = BM25Index()
    idx.build(
        [
            ("c1", "减脂期蛋白质摄入建议", {"text": "减脂期蛋白质摄入建议"}),
            ("c2", "胸痛应立即就医", {"text": "胸痛应立即就医"}),
        ]
    )
    hits = idx.search("蛋白质", top_k=2)
    assert hits and hits[0][0] == "c1"


def test_split_and_no_answer():
    chunks = split_text(
        "# 标题\n\n内容关于蛋白质。",
        document_id="d1",
        version_id="v1",
        title="t",
    )
    assert chunks
    packed = build_context([])
    assert packed["no_answer"] is True
