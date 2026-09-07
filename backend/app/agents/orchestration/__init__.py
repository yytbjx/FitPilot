"""渐进式三层意图路由 + ECD 计划 + DAG 编排 + 对抗审查 + Checkpoint 失败隔离。"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Literal

from app.agents.routing import Intent, RoutingDecision, route_intent
from app.core.progress import emit_progress


class RouteLayer(str, Enum):
    DETERMINISTIC = "layer1_deterministic"
    MODEL_ASSISTED = "layer2_model"
    MULTI_AGENT = "layer3_multi_agent"


@dataclass
class ProgressiveDecision:
    decision: RoutingDecision
    layer: RouteLayer
    execution_mode: Literal["workflow", "single_agent", "multi_agent"]
    reason: str = ""


def _looks_complex(text: str, intent: Intent) -> bool:
    if intent not in {"plan_create", "plan_adjust"}:
        # 跨域：知识 + 个人 / 计划关键词同现
        has_knowledge = bool(re.search(r"(蛋白|减脂|增肌|热量|怎么|如何|原则)", text or ""))
        has_personal = bool(re.search(r"(我的|档案|记录|最近|体重)", text or ""))
        has_plan = bool(re.search(r"(计划|安排|调整)", text or ""))
        return (has_knowledge and has_personal) or (has_personal and has_plan)
    return bool(
        re.search(
            r"(最近|两周|一周|体重|记录|联合|根据|调整|完成率|趋势|表现|同时|并且)",
            text or "",
        )
    )


def progressive_route(text: str, *, model_intent: Intent | None = None) -> ProgressiveDecision:
    """三层路由：
    L1 高置信确定性工作流 → workflow
    L2 模型辅助 / 中置信 → single_agent
    L3 复杂依赖 → multi_agent（ECD+DAG）
    """
    base = route_intent(text)
    intent = model_intent or base.primary_intent
    confidence = base.confidence

    # 模型辅助覆盖：仅当规则为 clarify 或低置信且模型给出明确标签
    if model_intent and model_intent != "clarify":
        if base.primary_intent == "clarify" or confidence < 0.7:
            intent = model_intent
            confidence = max(confidence, 0.72)
            base = RoutingDecision(
                primary_intent=intent,
                confidence=confidence,
                risk_level=base.risk_level,
                clarify_question=None,
            )
            if _looks_complex(text, intent):
                return ProgressiveDecision(
                    decision=base,
                    layer=RouteLayer.MULTI_AGENT,
                    execution_mode="multi_agent",
                    reason="model_assisted_complex",
                )
            return ProgressiveDecision(
                decision=base,
                layer=RouteLayer.MODEL_ASSISTED,
                execution_mode="single_agent",
                reason="model_assisted",
            )

    if base.primary_intent == "risk_or_medical":
        return ProgressiveDecision(
            decision=base,
            layer=RouteLayer.DETERMINISTIC,
            execution_mode="workflow",
            reason="safety_deterministic",
        )

    if base.primary_intent in {
        "plan_create",
        "plan_adjust",
        "personal_data_query",
        "workout_log_write",
        "diet_log_write",
        "small_talk",
        "unsupported",
        "knowledge_query",
    } and confidence >= 0.8 and not _looks_complex(text, base.primary_intent):
        return ProgressiveDecision(
            decision=base,
            layer=RouteLayer.DETERMINISTIC,
            execution_mode="workflow",
            reason="high_confidence_rule",
        )

    if _looks_complex(text, base.primary_intent if base.primary_intent != "clarify" else intent):
        # 复杂任务抬到 L3；若仍 clarify 则保持澄清
        if base.primary_intent == "clarify":
            return ProgressiveDecision(
                decision=base,
                layer=RouteLayer.MODEL_ASSISTED,
                execution_mode="single_agent",
                reason="needs_clarify",
            )
        return ProgressiveDecision(
            decision=base,
            layer=RouteLayer.MULTI_AGENT,
            execution_mode="multi_agent",
            reason="complex_dependencies",
        )

    if confidence < 0.8 or base.primary_intent == "clarify":
        return ProgressiveDecision(
            decision=base,
            layer=RouteLayer.MODEL_ASSISTED,
            execution_mode="single_agent",
            reason="mid_confidence",
        )

    return ProgressiveDecision(
        decision=base,
        layer=RouteLayer.DETERMINISTIC,
        execution_mode="workflow",
        reason="default_workflow",
    )


# ---------- ECD：实体-约束-依赖 ----------


@dataclass
class ECDTriple:
    entities: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    dependencies: list[tuple[str, str]] = field(default_factory=list)  # (from, to)


def extract_ecd(text: str, *, intent: Intent) -> ECDTriple:
    """规则抽取实体/约束/依赖（轻量，不依赖 LLM）。"""
    t = text or ""
    entities: dict[str, Any] = {"intent": intent}
    if re.search(r"减脂", t):
        entities["goal"] = "fat_loss"
    elif re.search(r"增肌", t):
        entities["goal"] = "muscle_gain"
    elif re.search(r"维持|保持", t):
        entities["goal"] = "maintain"
    if m := re.search(r"(\d+(?:\.\d+)?)\s*kg", t, re.I):
        entities["weight_kg"] = float(m.group(1))
    if re.search(r"蛋白", t):
        entities["topic"] = "protein"
    if re.search(r"饮食|膳食|热量", t):
        entities["domain_diet"] = True
    if re.search(r"训练|力量|有氧", t):
        entities["domain_training"] = True

    constraints: dict[str, Any] = {}
    if re.search(r"伤|膝盖|腰|疼|痛", t):
        constraints["injury_caution"] = True
    if re.search(r"忌口|过敏|素食", t):
        constraints["diet_restriction"] = True
    if re.search(r"两周|14\s*天", t):
        constraints["lookback_days"] = 14
    elif re.search(r"一周|7\s*天|最近", t):
        constraints["lookback_days"] = 7

    deps: list[tuple[str, str]] = []
    # 复杂计划：档案 → 日志 → 知识(可选) → 计划 → 一致性 → 审批
    if intent in {"plan_create", "plan_adjust"} or entities.get("domain_training") or entities.get(
        "domain_diet"
    ):
        deps.extend(
            [
                ("extract_profile", "fetch_logs"),
                ("fetch_logs", "plan_generate"),
                ("extract_profile", "plan_generate"),
                ("plan_generate", "consensus_check"),
                ("consensus_check", "human_approval"),
            ]
        )
        if entities.get("topic") or "知识" in t or "原则" in t:
            deps.append(("knowledge_retrieve", "plan_generate"))
            deps.append(("extract_profile", "knowledge_retrieve"))
    elif intent == "knowledge_query":
        deps.append(("knowledge_retrieve", "answer_synthesize"))
    elif intent == "personal_data_query":
        deps.extend(
            [
                ("extract_profile", "fetch_logs"),
                ("fetch_logs", "answer_synthesize"),
            ]
        )
    else:
        deps.append(("noop", "answer_synthesize"))

    return ECDTriple(entities=entities, constraints=constraints, dependencies=deps)


# ---------- DAG ----------


@dataclass
class DagNode:
    id: str
    agent: str
    depends_on: list[str] = field(default_factory=list)
    max_retries: int = 2
    checkpoint: dict[str, Any] = field(default_factory=dict)
    status: Literal["pending", "running", "done", "failed", "skipped"] = "pending"
    result: dict[str, Any] | None = None
    error: str | None = None
    attempts: int = 0


@dataclass
class DagPlan:
    nodes: dict[str, DagNode]
    ecd: ECDTriple
    intent: Intent

    def ready_nodes(self) -> list[DagNode]:
        out: list[DagNode] = []
        for node in self.nodes.values():
            if node.status != "pending":
                continue
            if all(self.nodes[d].status == "done" for d in node.depends_on if d in self.nodes):
                out.append(node)
        return out

    def failed_nodes(self) -> list[DagNode]:
        return [n for n in self.nodes.values() if n.status == "failed"]

    def reset_subtree(self, node_id: str) -> list[str]:
        """失败隔离：重置失败节点及依赖它的下游（保留无关已完成节点）。"""
        affected = {node_id}
        changed = True
        while changed:
            changed = False
            for n in self.nodes.values():
                if n.id in affected:
                    continue
                if any(d in affected for d in n.depends_on):
                    affected.add(n.id)
                    changed = True
        reset_ids: list[str] = []
        for nid in affected:
            node = self.nodes[nid]
            if node.status in {"failed", "done", "running", "skipped"}:
                node.status = "pending"
                node.result = None
                node.error = None
                # 保留 checkpoint 快照供重规划复用输入
                reset_ids.append(nid)
        return reset_ids


def build_dag_from_ecd(ecd: ECDTriple, *, intent: Intent) -> DagPlan:
    node_ids: set[str] = set()
    for a, b in ecd.dependencies:
        node_ids.add(a)
        node_ids.add(b)
    if not node_ids:
        node_ids = {"answer_synthesize"}

    agent_map = {
        "extract_profile": "personal_agent",
        "fetch_logs": "personal_agent",
        "knowledge_retrieve": "knowledge_agent",
        "plan_generate": "plan_agent",
        "consensus_check": "reviewer_agent",
        "human_approval": "approval_gate",
        "answer_synthesize": "synthesizer",
        "noop": "noop",
    }
    deps_map: dict[str, list[str]] = {nid: [] for nid in node_ids}
    for a, b in ecd.dependencies:
        if a not in deps_map[b]:
            deps_map[b].append(a)

    nodes = {
        nid: DagNode(id=nid, agent=agent_map.get(nid, "generic"), depends_on=deps_map.get(nid, []))
        for nid in node_ids
    }
    return DagPlan(nodes=nodes, ecd=ecd, intent=intent)


NodeHandler = Callable[[DagNode, DagPlan, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass
class AdversarialReview:
    ok: bool
    conflicts: list[str] = field(default_factory=list)
    consensus: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def adversarial_review(plan: DagPlan, *, context: dict[str, Any]) -> AdversarialReview:
    """每步汇总后的对抗性审查：实体对齐 / 约束 / 依赖完整性。"""
    conflicts: list[str] = []
    notes: list[str] = []
    results = {nid: n.result or {} for nid, n in plan.nodes.items() if n.status == "done"}

    # 依赖完整性
    for n in plan.nodes.values():
        if n.status == "done":
            for d in n.depends_on:
                dep = plan.nodes.get(d)
                if dep is None or dep.status != "done":
                    conflicts.append(f"依赖未完成: {n.id} <- {d}")

    # 实体对齐：档案体重 vs 计划声明
    profile = (results.get("extract_profile") or {}).get("profile") or context.get("user_profile") or {}
    plan_out = results.get("plan_generate") or {}
    if profile.get("weight_kg") and plan_out.get("weight_kg"):
        try:
            if abs(float(profile["weight_kg"]) - float(plan_out["weight_kg"])) > 0.6:
                conflicts.append("实体冲突: weight_kg 档案与计划不一致")
        except (TypeError, ValueError):
            pass

    # 约束：伤病时计划不得含高冲击词（启发式）
    if plan.ecd.constraints.get("injury_caution"):
        blob = str(plan_out)
        if re.search(r"跳箱|爆发|最大重量|力竭", blob):
            conflicts.append("约束冲突: 伤病谨慎下出现高冲击安排")

    # 置信度加权共识
    confs = []
    for r in results.values():
        if "confidence" in r:
            try:
                confs.append(float(r["confidence"]))
            except (TypeError, ValueError):
                pass
    consensus = {
        "entities": plan.ecd.entities,
        "constraints": plan.ecd.constraints,
        "avg_confidence": sum(confs) / len(confs) if confs else 0.7,
        "node_results": {k: {"ok": bool(v.get("ok", True)), "keys": list(v.keys())[:12]} for k, v in results.items()},
    }
    if conflicts:
        notes.append("对抗审查发现冲突，需局部重规划或人工确认")
    else:
        notes.append("结构化共识通过")
    return AdversarialReview(ok=not conflicts, conflicts=conflicts, consensus=consensus, notes=notes)


async def run_dag(
    plan: DagPlan,
    *,
    handlers: dict[str, NodeHandler],
    context: dict[str, Any],
    max_replans: int = 2,
) -> dict[str, Any]:
    """轻量编排器：无依赖节点并行；失败隔离 + 局部重规划。"""
    replans = 0
    reviews: list[dict[str, Any]] = []

    while True:
        # 推进直到无 ready 或存在失败
        while True:
            ready = plan.ready_nodes()
            if not ready:
                break
            emit_progress(
                stage="orchestrator",
                title="DAG 并行调度",
                detail=f"ready={[n.id for n in ready]}",
                tool="dag_orchestrator",
            )

            async def _run_one(node: DagNode) -> None:
                node.status = "running"
                node.attempts += 1
                node.checkpoint = {
                    "inputs": {d: (plan.nodes[d].result or {}) for d in node.depends_on if d in plan.nodes},
                    "attempt": node.attempts,
                }
                handler = handlers.get(node.id) or handlers.get(node.agent) or handlers.get("default")
                if handler is None:
                    node.status = "failed"
                    node.error = f"no handler for {node.id}"
                    return
                try:
                    result = await handler(node, plan, context)
                    node.result = result
                    if result.get("ok") is False:
                        node.status = "failed"
                        node.error = str(result.get("error") or "handler returned ok=false")
                    else:
                        node.status = "done"
                except Exception as exc:  # noqa: BLE001
                    node.status = "failed"
                    node.error = str(exc)

            await asyncio.gather(*[_run_one(n) for n in ready])

            failed = plan.failed_nodes()
            if failed:
                break
            if not plan.ready_nodes() and all(
                n.status in {"done", "skipped"} for n in plan.nodes.values()
            ):
                break
            # 若仍有 pending 但无 ready → 死锁
            if plan.ready_nodes() == [] and any(n.status == "pending" for n in plan.nodes.values()):
                for n in plan.nodes.values():
                    if n.status == "pending":
                        n.status = "failed"
                        n.error = "dependency deadlock"
                break

        failed = plan.failed_nodes()
        if failed and replans < max_replans:
            for fn in failed:
                if fn.attempts > fn.max_retries:
                    continue
                reset_ids = plan.reset_subtree(fn.id)
                emit_progress(
                    stage="orchestrator",
                    title="失败隔离与局部重规划",
                    detail=f"reset={reset_ids} error={fn.error}",
                    tool="dag_orchestrator",
                )
            replans += 1
            # 超过重试的保持 failed
            for fn in list(plan.failed_nodes()):
                if fn.attempts > fn.max_retries and fn.status == "pending":
                    fn.status = "failed"
            continue

        review = adversarial_review(plan, context=context)
        reviews.append(
            {
                "ok": review.ok,
                "conflicts": review.conflicts,
                "notes": review.notes,
                "consensus": review.consensus,
            }
        )
        if not review.ok and replans < max_replans:
            # 冲突时重置 consensus / plan_generate 下游
            target = "plan_generate" if "plan_generate" in plan.nodes else next(iter(plan.nodes))
            plan.reset_subtree(target)
            replans += 1
            continue
        break

    done = {nid: n.result for nid, n in plan.nodes.items() if n.status == "done"}
    failed_final = [{"id": n.id, "error": n.error, "attempts": n.attempts} for n in plan.failed_nodes()]
    return {
        "ok": not failed_final and (not reviews or reviews[-1].get("ok", True)),
        "results": done,
        "failed": failed_final,
        "reviews": reviews,
        "replans": replans,
        "ecd": {
            "entities": plan.ecd.entities,
            "constraints": plan.ecd.constraints,
            "dependencies": plan.ecd.dependencies,
        },
    }
