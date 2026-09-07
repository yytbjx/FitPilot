"""评测集规模选择：large（evals/large/）与 small/fewshot（evals/fewshot/）。"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Literal

SuiteSet = Literal["large", "small", "fewshot"]

# config suites key → 文件名
SUITE_FILES: dict[str, str] = {
    "parsing": "parsing_cases.json",
    "retrieval": "golden_rag.json",
    "retrieval_offline": "golden_rag_offline.json",
    "no_answer": "no_answer_cases.json",
    "no_answer_offline": "golden_rag_offline.json",
    "generation": "generation_cases.json",
    "generation_online": "generation_online_cases.json",
    "agent": "agent_routing_cases.json",
    "plan": "plan_cases.json",
    "meal": "meal_cases.json",
    "safety": "safety_cases.json",
    "context_kv": "context_kv_cases.json",
}

# 单层命令默认文件名
LAYER_DEFAULT_FILES: dict[str, str] = {
    "retrieval": "golden_rag.json",
    "no_answer": "no_answer_cases.json",
    "agent": "agent_routing_cases.json",
}


def normalize_suite_set(value: str) -> SuiteSet:
    v = (value or "large").strip().lower()
    if v in {"small", "fewshot", "mini"}:
        return "small"
    if v in {"large", "full", "big"}:
        return "large"
    raise ValueError("suite-set 仅支持 large|small（fewshot 为 small 别名）")


def suite_root(repo_root: Path, suite_set: str) -> Path:
    kind = normalize_suite_set(suite_set)
    if kind == "small":
        return repo_root / "evals" / "fewshot"
    return repo_root / "evals" / "large"


def resolve_suite_path(repo_root: Path, suite_set: str, filename: str) -> Path:
    return suite_root(repo_root, suite_set) / filename


def suite_rel_paths(repo_root: Path, suite_set: str) -> dict[str, str]:
    """返回相对仓库根的正斜杠路径，写入 eval_config.suites。"""
    root = suite_root(repo_root, suite_set)
    out: dict[str, str] = {}
    for key, fname in SUITE_FILES.items():
        rel = (root / fname).resolve().relative_to(repo_root.resolve())
        out[key] = rel.as_posix()
    return out


def apply_suite_set_to_config(
    cfg: dict[str, Any],
    *,
    repo_root: Path,
    suite_set: str,
) -> dict[str, Any]:
    """深拷贝配置并把 suites / dataset_path 切到指定规模。"""
    out = copy.deepcopy(cfg) if cfg else {}
    paths = suite_rel_paths(repo_root, suite_set)
    out["suites"] = {**(out.get("suites") or {}), **paths}
    params = dict(out.get("parameters") or {})
    params["dataset_path"] = paths["retrieval"]
    params["suite_set"] = normalize_suite_set(suite_set)
    out["parameters"] = params
    return out
