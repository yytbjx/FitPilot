"""长上下文 / KV Cache / 编排专项离线评测（不依赖 Qdrant/Ollama）。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.agents.context_assembly import (
    assemble_context,
    build_stable_prefix,
    longest_common_prefix_ratio,
    select_fragments_path,
)
from app.agents.memory.conversation_memory import MemoryFragment, estimate_tokens, summarize_turn
from app.agents.orchestration import (
    build_dag_from_ecd,
    extract_ecd,
    progressive_route,
)


@dataclass
class CaseResult:
    case_id: str
    ok: bool
    detail: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContextKvEvalResult:
    cases: list[CaseResult] = field(default_factory=list)
    ok: bool = False
    avg_reduction: float = 0.0
    avg_recall_at_budget: float = 0.0
    avg_lcp: float = 0.0
    route_accuracy: float = 0.0
    orchestrator_pass: float = 0.0
    min_reduction: float = 0.1
    min_recall_at_budget: float = 0.6
    min_lcp: float = 0.9
    min_route_accuracy: float = 0.8
    min_orchestrator_pass: float = 0.75

    def summary_text(self) -> str:
        return (
            f"reduction={self.avg_reduction:.3f} recall@budget={self.avg_recall_at_budget:.3f} "
            f"lcp={self.avg_lcp:.3f} route_acc={self.route_accuracy:.3f} "
            f"orch_pass={self.orchestrator_pass:.3f} cases={len(self.cases)} "
            f"ok={self.ok}"
        )


def _frag(turn: int, role: str, content: str, score: float = 0.5) -> MemoryFragment:
    summary = summarize_turn(role, content)
    return MemoryFragment(
        message_id=f"m{turn}",
        turn_index=turn,
        role=role,
        content=content,
        summary=summary,
        score=score,
        tokens=estimate_tokens(summary),
    )


def _eval_context_case(case: dict[str, Any]) -> CaseResult:
    cid = str(case.get("id") or "ctx")
    query = str(case.get("query") or "")
    history = case.get("history") or []
    relevant_turns = set(int(x) for x in (case.get("relevant_turns") or []))
    budget = int(case.get("token_budget") or 512)
    core_k = int(case.get("core_k") or 4)

    frags = [
        _frag(int(h["turn"]), str(h.get("role") or "user"), str(h.get("content") or ""), float(h.get("score") or 0.4))
        for h in history
    ]
    # 提升相关 turn 的 score
    for f in frags:
        if f.turn_index in relevant_turns:
            f.score = max(f.score, 0.85)

    core = frags[-core_k:] if frags else []
    older = frags[:-core_k] if len(frags) > core_k else []
    assembled = assemble_context(
        query=query,
        core=core,
        recall_candidates=older,
        evidence=str(case.get("evidence") or "证据片段A"),
        user_id=1,
        token_budget=budget,
    )
    selected_turns = {f.turn_index for f in assembled.selected_fragments} | {f.turn_index for f in core}
    hit = len(relevant_turns & selected_turns)
    recall = hit / len(relevant_turns) if relevant_turns else 1.0
    prefix_a = build_stable_prefix(user_id=1)
    prefix_b = build_stable_prefix(user_id=1)
    lcp = longest_common_prefix_ratio(prefix_a, prefix_b)
    ok = assembled.reduction_ratio >= float(case.get("min_reduction") or 0.2) and recall >= float(
        case.get("min_recall") or 0.5
    )
    return CaseResult(
        case_id=cid,
        ok=ok,
        detail=f"reduction={assembled.reduction_ratio:.3f} recall={recall:.3f}",
        metrics={
            "reduction_ratio": assembled.reduction_ratio,
            "recall_at_budget": recall,
            "lcp_ratio": lcp,
            "total_tokens": assembled.total_tokens,
            "baseline_tokens": assembled.baseline_tokens,
            "selected_turns": sorted(selected_turns),
        },
    )


def _eval_kv_case(case: dict[str, Any]) -> CaseResult:
    cid = str(case.get("id") or "kv")
    # 两次装配：仅证据变化，前缀应完全一致 → LCP=1
    q = str(case.get("query") or "蛋白质怎么吃")
    core = [_frag(0, "user", "我在减脂"), _frag(1, "assistant", "好的，注意蛋白")]
    a1 = assemble_context(query=q, core=core, recall_candidates=[], evidence="证据1：每日蛋白…", user_id=7)
    a2 = assemble_context(query=q, core=core, recall_candidates=[], evidence="证据2：不同内容…", user_id=7)
    lcp = longest_common_prefix_ratio(a1.system_prompt, a2.system_prompt)
    # 路径优化：选高相关短片段
    cands = [
        _frag(10, "user", "无关闲聊" * 20, 0.1),
        _frag(11, "user", "蛋白摄入目标", 0.95),
        _frag(12, "assistant", "按体重计算", 0.9),
        _frag(20, "user", "完全无关的股票问题" * 15, 0.05),
    ]
    chosen, div = select_fragments_path(cands, token_budget=int(case.get("token_budget") or 80))
    chosen_turns = [c.turn_index for c in chosen]
    prefer_ok = 11 in chosen_turns or 12 in chosen_turns
    ok = lcp >= float(case.get("min_lcp") or 0.99) and prefer_ok
    return CaseResult(
        case_id=cid,
        ok=ok,
        detail=f"lcp={lcp:.3f} chosen={chosen_turns} div={div:.3f}",
        metrics={"lcp_ratio": lcp, "chosen_turns": chosen_turns, "prefix_divergence_cost": div},
    )


def _eval_route_case(case: dict[str, Any]) -> CaseResult:
    cid = str(case.get("id") or "route")
    text = str(case.get("text") or "")
    expect_intent = str(case.get("expect_intent") or "")
    expect_mode = case.get("expect_mode")
    expect_layer = case.get("expect_layer")
    prog = progressive_route(text)
    ok = True
    if expect_intent and prog.decision.primary_intent != expect_intent:
        ok = False
    if expect_mode and prog.execution_mode != expect_mode:
        ok = False
    if expect_layer and prog.layer.value != expect_layer:
        ok = False
    return CaseResult(
        case_id=cid,
        ok=ok,
        detail=f"intent={prog.decision.primary_intent} mode={prog.execution_mode} layer={prog.layer.value}",
        metrics={
            "intent": prog.decision.primary_intent,
            "mode": prog.execution_mode,
            "layer": prog.layer.value,
            "confidence": prog.decision.confidence,
        },
    )


def _eval_orch_case(case: dict[str, Any]) -> CaseResult:
    cid = str(case.get("id") or "orch")
    text = str(case.get("text") or "")
    intent = str(case.get("intent") or "plan_adjust")
    ecd = extract_ecd(text, intent=intent)  # type: ignore[arg-type]
    dag = build_dag_from_ecd(ecd, intent=intent)  # type: ignore[arg-type]
    expect_nodes = set(case.get("expect_nodes") or [])
    got = set(dag.nodes.keys())
    # 依赖方向检查
    dep_ok = True
    for a, b in ecd.dependencies:
        if a in dag.nodes and b in dag.nodes:
            if a not in dag.nodes[b].depends_on and a != b:
                # build_dag maps edge a->b as b depends on a
                if a not in dag.nodes[b].depends_on:
                    dep_ok = False
    node_ok = expect_nodes.issubset(got) if expect_nodes else bool(got)
    # 无依赖节点应可并行：extract_profile 与 knowledge_retrieve 若同时存在且互不依赖
    ready0 = [n.id for n in dag.ready_nodes()]
    ok = node_ok and dep_ok and bool(ready0)
    return CaseResult(
        case_id=cid,
        ok=ok,
        detail=f"nodes={sorted(got)} ready0={ready0}",
        metrics={"nodes": sorted(got), "ready": ready0, "deps": ecd.dependencies},
    )


def run_context_kv_eval(suite_path: Path) -> ContextKvEvalResult:
    data = json.loads(suite_path.read_text(encoding="utf-8"))
    cases = data if isinstance(data, list) else list(data.get("cases") or [])
    result = ContextKvEvalResult()
    reductions: list[float] = []
    recalls: list[float] = []
    lcps: list[float] = []
    route_ok = 0
    route_n = 0
    orch_ok = 0
    orch_n = 0

    for case in cases:
        kind = str(case.get("kind") or "context")
        if kind == "kv_cache":
            cr = _eval_kv_case(case)
            lcps.append(float(cr.metrics.get("lcp_ratio") or 0))
        elif kind == "routing":
            cr = _eval_route_case(case)
            route_n += 1
            route_ok += int(cr.ok)
        elif kind == "orchestrator":
            cr = _eval_orch_case(case)
            orch_n += 1
            orch_ok += int(cr.ok)
        else:
            cr = _eval_context_case(case)
            reductions.append(float(cr.metrics.get("reduction_ratio") or 0))
            recalls.append(float(cr.metrics.get("recall_at_budget") or 0))
            lcps.append(float(cr.metrics.get("lcp_ratio") or 0))
        result.cases.append(cr)

    result.avg_reduction = sum(reductions) / len(reductions) if reductions else 1.0
    result.avg_recall_at_budget = sum(recalls) / len(recalls) if recalls else 1.0
    result.avg_lcp = sum(lcps) / len(lcps) if lcps else 1.0
    result.route_accuracy = route_ok / route_n if route_n else 1.0
    result.orchestrator_pass = orch_ok / orch_n if orch_n else 1.0
    result.ok = (
        result.avg_reduction >= result.min_reduction
        and result.avg_recall_at_budget >= result.min_recall_at_budget
        and result.avg_lcp >= result.min_lcp
        and result.route_accuracy >= result.min_route_accuracy
        and result.orchestrator_pass >= result.min_orchestrator_pass
        and all(c.ok for c in result.cases)
    )
    return result
