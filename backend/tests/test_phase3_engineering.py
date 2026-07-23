"""子图编译、UoW、索引版本与 CI 门禁。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.agents.workflows.graphs import (
    build_knowledge_subgraph,
    build_logging_subgraph,
    build_safety_subgraph,
)
from app.agents.workflows.graphs.safety_graph import invoke_safety_mode
from app.eval.ci_gate import run_ci_gates
from app.infrastructure.persistence.uow import SqlAlchemyUnitOfWork
from app.rag.knowledge_lifecycle import (
    append_index_version,
    find_index_version,
    list_index_versions,
    set_active_index_version,
)


def test_compile_knowledge_and_safety_subgraphs():
    kg = build_knowledge_subgraph()
    sg = build_safety_subgraph(mode="clarify")
    lg = build_logging_subgraph()
    assert kg is not None and sg is not None and lg is not None


def test_safety_subgraph_invoke():
    out = asyncio.run(
        invoke_safety_mode(
            {"original_request": "胸痛还能练吗", "user_id": 1, "tool_results": [], "events": []},
            mode="safety",
        )
    )
    assert out.get("final_status") == "blocked_safety"


def test_logging_subgraph_invoke():
    graph = build_logging_subgraph()
    out = asyncio.run(graph.ainvoke({"original_request": "我练了", "user_id": 1, "tool_results": [], "events": []}))
    assert out.get("final_status") == "completed"
    assert "记录" in (out.get("reply") or "")


def test_uow_exposes_repositories():
    class _Sess:
        async def commit(self):
            return None

        async def rollback(self):
            return None

    uow = SqlAlchemyUnitOfWork(_Sess())  # type: ignore[arg-type]
    assert uow.plans is not None
    assert uow.agent_tasks is not None


def test_index_version_list_and_find(tmp_path: Path, monkeypatch):
    from app.rag import knowledge_lifecycle as kl

    meta_file = tmp_path / "index_versions.jsonl"
    active = tmp_path / "active_index_version.json"

    monkeypatch.setattr(kl, "index_meta_path", lambda: meta_file)
    monkeypatch.setattr(kl, "active_index_pointer_path", lambda: active)

    v1 = {"index_version": "idx_aaa", "mode": "reset", "status": "ready"}
    v2 = {"index_version": "idx_bbb", "mode": "incremental", "status": "ready"}
    append_index_version(v1)
    append_index_version(v2)
    set_active_index_version(v2)

    vers = list_index_versions()
    assert len(vers) == 2
    assert find_index_version("idx_aaa")["mode"] == "reset"
    assert json.loads(active.read_text(encoding="utf-8"))["index_version"] == "idx_bbb"


def test_ci_gates_offline_pass():
    report = run_ci_gates()
    assert report.layers, "应至少跑一层离线门禁"
    # 若失败打印摘要便于排查
    if not report.ok:
        pytest.fail(report.summary_text())
