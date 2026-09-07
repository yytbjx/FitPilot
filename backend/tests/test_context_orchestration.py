"""分层记忆 / KV 装配 / 三层编排 单测（纯离线）。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.agents.context_assembly import (
    assemble_context,
    build_stable_prefix,
    longest_common_prefix_ratio,
    select_fragments_path,
)
from app.agents.memory.conversation_memory import MemoryFragment, estimate_tokens, summarize_turn
from app.agents.orchestration import (
    DagNode,
    adversarial_review,
    build_dag_from_ecd,
    extract_ecd,
    progressive_route,
    run_dag,
)
from app.eval.context_kv_eval import run_context_kv_eval


def test_stable_prefix_is_deterministic():
    a = build_stable_prefix(user_id=1)
    b = build_stable_prefix(user_id=1)
    assert a == b
    assert longest_common_prefix_ratio(a, b) == 1.0


def test_fragment_path_prefers_relevant_short():
    cands = [
        MemoryFragment("a", 1, "user", "无关" * 40, summarize_turn("user", "无关" * 40), score=0.1),
        MemoryFragment("b", 2, "user", "蛋白质目标", summarize_turn("user", "蛋白质目标"), score=0.95),
        MemoryFragment("c", 3, "assistant", "按体重估算", summarize_turn("assistant", "按体重估算"), score=0.9),
    ]
    for f in cands:
        f.tokens = estimate_tokens(f.summary)
    chosen, _ = select_fragments_path(cands, token_budget=60)
    turns = {x.turn_index for x in chosen}
    assert 2 in turns or 3 in turns


def test_assemble_puts_evidence_last_and_reduces():
    core = [
        MemoryFragment("1", 0, "user", "我在减脂", "user: 我在减脂", score=1.0),
        MemoryFragment("2", 1, "assistant", "好的", "assistant: 好的", score=1.0),
    ]
    older = [
        MemoryFragment("3", 2, "user", "完全无关的闲聊内容" * 30, "user: 闲聊…", score=0.05),
        MemoryFragment("4", 3, "user", "蛋白怎么吃", "user: 蛋白怎么吃", score=0.9),
    ]
    for f in [*core, *older]:
        f.tokens = estimate_tokens(f.summary or f.content)
    r = assemble_context(
        query="减脂蛋白质",
        core=core,
        recall_candidates=older,
        evidence="指南证据……",
        user_id=9,
        token_budget=200,
    )
    kinds = [b.kind for b in r.blocks]
    assert kinds[0] == "stable_prefix"
    assert "evidence" in kinds
    assert kinds.index("evidence") > kinds.index("query")
    assert r.reduction_ratio >= 0.0
    assert r.total_tokens > 0


def test_progressive_route_layers():
    simple = progressive_route("请生成一份训练计划")
    assert simple.decision.primary_intent == "plan_create"
    assert simple.execution_mode == "workflow"

    complex_ = progressive_route("根据我最近两周的训练记录调整饮食和训练计划")
    assert complex_.decision.primary_intent == "plan_adjust"
    assert complex_.execution_mode == "multi_agent"

    know = progressive_route("减脂期蛋白质怎么安排？")
    assert know.decision.primary_intent == "knowledge_query"


def test_ecd_and_dag_parallel_ready():
    ecd = extract_ecd("根据最近两周记录调整减脂计划", intent="plan_adjust")
    dag = build_dag_from_ecd(ecd, intent="plan_adjust")
    assert "plan_generate" in dag.nodes
    ready = {n.id for n in dag.ready_nodes()}
    assert "extract_profile" in ready


def test_dag_failure_isolation_and_review():
    ecd = extract_ecd("联合调整计划", intent="plan_adjust")
    dag = build_dag_from_ecd(ecd, intent="plan_adjust")

    async def ok_handler(node: DagNode, plan, ctx):
        return {"ok": True, "confidence": 0.9, "profile": {"weight_kg": 70}}

    async def fail_once(node: DagNode, plan, ctx):
        if node.attempts <= 1:
            return {"ok": False, "error": "transient"}
        return {"ok": True, "confidence": 0.8, "weight_kg": 70}

    handlers = {
        "extract_profile": ok_handler,
        "fetch_logs": ok_handler,
        "plan_generate": fail_once,
        "consensus_check": ok_handler,
        "human_approval": ok_handler,
        "knowledge_retrieve": ok_handler,
        "default": ok_handler,
    }
    out = asyncio.run(run_dag(dag, handlers=handlers, context={}))
    assert out["ok"] is True
    assert out["replans"] >= 1
    review = adversarial_review(dag, context={})
    assert isinstance(review.conflicts, list)


def test_context_kv_suite_offline():
    root = Path(__file__).resolve().parents[2]
    path = root / "evals" / "fewshot" / "context_kv_cases.json"
    r = run_context_kv_eval(path)
    assert r.avg_lcp >= 0.9
    assert r.route_accuracy >= 0.8
    assert r.orchestrator_pass >= 0.75
    assert r.ok, r.summary_text()
