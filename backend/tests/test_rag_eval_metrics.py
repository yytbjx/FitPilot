"""评估辅助函数单测（不依赖 Qdrant）。"""

from app.eval.rag_eval import _first_relevant_rank, load_eval_config
from pathlib import Path


def test_first_relevant_rank():
    chunks = [
        {"text": "无关内容", "document_id": "a"},
        {"text": "减脂期蛋白质建议 1.6-2.2", "document_id": "b"},
    ]
    rank, matched = _first_relevant_rank(chunks, ["蛋白", "1.6"])
    assert rank == 2
    assert matched


def test_load_eval_config_yaml():
    cfg = load_eval_config(Path(__file__).resolve().parents[2] / "evals" / "eval_config.yaml")
    assert "parameters" in cfg
    assert 1 in cfg["parameters"]["top_k_list"] or cfg["parameters"]["top_k_list"][0] == 1
