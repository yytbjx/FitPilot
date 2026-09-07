"""suite_set 路径解析。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.eval.suite_set import (
    apply_suite_set_to_config,
    normalize_suite_set,
    resolve_suite_path,
    suite_rel_paths,
)


def test_normalize_suite_set_aliases() -> None:
    assert normalize_suite_set("large") == "large"
    assert normalize_suite_set("small") == "small"
    assert normalize_suite_set("fewshot") == "small"
    with pytest.raises(ValueError):
        normalize_suite_set("medium")


def test_resolve_paths_point_to_correct_dirs() -> None:
    root = Path(__file__).resolve().parents[2]
    large = resolve_suite_path(root, "large", "golden_rag.json")
    small = resolve_suite_path(root, "small", "golden_rag.json")
    assert large == root / "evals" / "large" / "golden_rag.json"
    assert small == root / "evals" / "fewshot" / "golden_rag.json"
    assert large.exists()
    assert small.exists()


def test_apply_suite_set_rewrites_config_suites() -> None:
    root = Path(__file__).resolve().parents[2]
    cfg = apply_suite_set_to_config({}, repo_root=root, suite_set="small")
    assert cfg["suites"]["retrieval"].endswith("fewshot/golden_rag.json")
    assert cfg["parameters"]["suite_set"] == "small"
    paths = suite_rel_paths(root, "large")
    assert paths["parsing"] == "evals/large/parsing_cases.json"
