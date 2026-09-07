"""多层评估统一编排（解析 / 检索 / 拒答 / 生成 / Agent / 计划 / 食谱 / 安全）。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.eval.agent_eval import run_agent_eval
from app.eval.context_kv_eval import run_context_kv_eval
from app.eval.generation_eval import run_generation_eval
from app.eval.generation_online_eval import run_generation_online_eval
from app.eval.meal_eval import run_meal_eval
from app.eval.no_answer_eval import run_no_answer_eval
from app.eval.parsing_eval import run_parsing_eval
from app.eval.plan_eval import run_plan_eval
from app.eval.progress import layer_banner
from app.eval.rag_eval import run_rag_eval
from app.eval.safety_eval import run_safety_eval

LAYER_ORDER = [
    ("parsing", "文档解析"),
    ("retrieval", "RAG 检索"),
    ("no_answer", "拒答/无答案"),
    ("generation", "生成与引用"),
    ("generation_online", "生成在线裁判"),
    ("agent", "Agent 路由"),
    ("plan", "训练计划"),
    ("meal", "食谱优化"),
    ("safety", "安全与联合调整"),
    ("context_kv", "长上下文与编排"),
]


@dataclass
class LayerReport:
    layer: str
    title: str
    ok: bool
    summary: str
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class FullEvalReport:
    layers: list[LayerReport] = field(default_factory=list)
    ok: bool = False
    config_path: str = ""

    def summary_text(self) -> str:
        lines = ["=== FitPilot 多层评估 ==="]
        for lr in self.layers:
            mark = "PASS" if lr.ok else "FAIL"
            lines.append(f"[{mark}] Layer {lr.layer} {lr.title}: {lr.summary}")
        lines.append(f"overall={'PASS' if self.ok else 'FAIL'}")
        return "\n".join(lines)

    def to_markdown(self) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        lines = [
            "# FitPilot Full Eval Report",
            "",
            f"- generated_at: `{ts}`",
            f"- config: `{self.config_path}`",
            f"- overall: **{'PASS' if self.ok else 'FAIL'}**",
            "",
        ]
        for lr in self.layers:
            lines.append(f"## {lr.layer} — {lr.title}")
            lines.append(f"- status: **{'PASS' if lr.ok else 'FAIL'}**")
            lines.append(f"- summary: {lr.summary}")
            if lr.metrics:
                # 报告里省略冗长 cases，完整内容在 JSON
                slim = {k: v for k, v in lr.metrics.items() if k != "cases"}
                lines.append(f"- metrics: `{json.dumps(slim, ensure_ascii=False)}`")
                cases = lr.metrics.get("cases") or []
                lines.append(f"- cases: **{len(cases)}**")
            lines.append("")
        return "\n".join(lines)


def _load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    text = config_path.read_text(encoding="utf-8")
    if config_path.suffix in {".yaml", ".yml"}:
        import yaml

        return yaml.safe_load(text) or {}
    return json.loads(text)


def _cases_payload(cases: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for c in cases or []:
        if is_dataclass(c):
            out.append(asdict(c))
        elif isinstance(c, dict):
            out.append(c)
        else:
            out.append({"value": str(c)})
    return out


def run_full_eval(
    *,
    config_path: Path,
    repo_root: Path | None = None,
    out_path: Path | None = None,
    md_path: Path | None = None,
    suite_set: str | None = None,
) -> FullEvalReport:
    root = repo_root or config_path.parent.parent
    cfg = _load_config(config_path)
    if suite_set:
        from app.eval.suite_set import apply_suite_set_to_config

        cfg = apply_suite_set_to_config(cfg, repo_root=root, suite_set=suite_set)
    modules = cfg.get("modules") or {}
    suites = cfg.get("suites") or {}
    params = cfg.get("parameters") or {}
    thresholds = cfg.get("thresholds") if isinstance(cfg.get("thresholds"), dict) else {}
    report = FullEvalReport(config_path=str(config_path))

    def _suite(name: str, default: str) -> Path:
        rel = suites.get(name) or default
        p = Path(rel)
        return p if p.is_absolute() else root / p

    def _mod_enabled(name: str, default: bool = True) -> bool:
        block = modules.get(name)
        if not isinstance(block, dict):
            return default
        return bool(block.get("enabled", default))

    # Layer 1 — parsing
    if _mod_enabled("parsing", True):
        path = _suite("parsing", "evals/large/parsing_cases.json")
        if path.exists():
            layer_banner("1", "文档解析")
            r = run_parsing_eval(path)
            report.layers.append(
                LayerReport(
                    layer="1",
                    title="文档解析",
                    ok=r.ok,
                    summary=r.summary_text(),
                    metrics={"pass_rate": r.pass_rate, "cases": _cases_payload(r.cases)},
                )
            )

    # Layer 2 — retrieval
    if _mod_enabled("retrieval", True):
        suite = _suite("retrieval", params.get("dataset_path") or "evals/large/golden_rag.json")
        if suite.exists():
            layer_banner("2", "RAG 检索")
            r = run_rag_eval(
                suite_path=suite,
                top_k=int(params.get("top_k") or 4),
                config_path=config_path if config_path.exists() else None,
            )
            report.layers.append(
                LayerReport(
                    layer="2",
                    title="RAG 检索",
                    ok=r.ok,
                    summary=r.summary_text(),
                    metrics={
                        "hit_rate": r.hit_rate,
                        "mrr": r.mrr,
                        "citation_rate": r.citation_rate,
                        "hit_at_k": r.hit_at_k,
                        "precision_at_k": r.precision_at_k,
                        "term_recall_at_k": r.term_recall_at_k,
                        "ndcg_at_k": r.ndcg_at_k,
                        "anchor_chunk_at_k": r.anchor_chunk_at_k,
                        "anchor_doc_at_k": r.anchor_doc_at_k,
                        "anchor_chunk_cases": r.anchor_chunk_cases,
                        "anchor_doc_cases": r.anchor_doc_cases,
                        "cases": _cases_payload(r.cases),
                    },
                )
            )

    # Layer 2b — no_answer
    if _mod_enabled("no_answer", True):
        path = _suite("no_answer", "evals/large/no_answer_cases.json")
        if path.exists():
            layer_banner("2b", "拒答/无答案")
            r = run_no_answer_eval(path)
            report.layers.append(
                LayerReport(
                    layer="2b",
                    title="拒答/无答案",
                    ok=r.ok,
                    summary=r.summary_text(),
                    metrics={
                        "recall": r.recall,
                        "precision": r.precision,
                        "cases": _cases_payload(r.cases),
                    },
                )
            )

    # Layer 3 — generation (offline rules + e2e retrieve)
    if _mod_enabled("generation", True):
        path = _suite("generation", "evals/large/generation_cases.json")
        if path.exists():
            layer_banner("3", "生成与引用")
            r = run_generation_eval(path)
            report.layers.append(
                LayerReport(
                    layer="3",
                    title="生成与引用",
                    ok=r.ok,
                    summary=r.summary_text(),
                    metrics={"pass_rate": r.pass_rate, "cases": _cases_payload(r.cases)},
                )
            )

    # Layer 3b — generation online (LLM-as-judge)
    if _mod_enabled("generation_online", False):
        path = _suite("generation_online", "evals/large/generation_online_cases.json")
        if path.exists():
            layer_banner("3b", "生成在线裁判")
            r = run_generation_online_eval(path)
            report.layers.append(
                LayerReport(
                    layer="3b",
                    title="生成在线裁判",
                    ok=r.ok,
                    summary=r.summary_text(),
                    metrics={
                        "pass_rate": r.pass_rate,
                        "used_llm": r.used_llm,
                        "cases": _cases_payload(r.cases),
                    },
                )
            )

    # Layer 4 — agent
    if _mod_enabled("agent", True):
        path = _suite("agent", "evals/large/agent_routing_cases.json")
        if path.exists():
            layer_banner("4", "Agent 路由")
            r = run_agent_eval(path)
            agent_th = thresholds.get("agent") if isinstance(thresholds.get("agent"), dict) else {}
            # config 阈值可覆盖套件（若明确给出）
            if "min_accuracy" in agent_th:
                r.min_accuracy = float(agent_th["min_accuracy"])
            if "min_macro_f1" in agent_th:
                r.min_macro_f1 = float(agent_th["min_macro_f1"])
            report.layers.append(
                LayerReport(
                    layer="4",
                    title="Agent 路由",
                    ok=r.ok,
                    summary=r.summary_text(),
                    metrics={
                        "accuracy": r.accuracy,
                        "macro_f1": r.macro_f1,
                        "cases": _cases_payload(r.cases),
                    },
                )
            )

    # Layer 5 — plan
    if _mod_enabled("plan", True):
        path = _suite("plan", "evals/large/plan_cases.json")
        if path.exists():
            layer_banner("5", "训练计划")
            r = run_plan_eval(path)
            report.layers.append(
                LayerReport(
                    layer="5",
                    title="训练计划",
                    ok=r.ok,
                    summary=r.summary_text(),
                    metrics={"pass_rate": r.pass_rate, "cases": _cases_payload(r.cases)},
                )
            )

    # Layer 6 — meal
    if _mod_enabled("meal", True):
        path = _suite("meal", "evals/large/meal_cases.json")
        if path.exists():
            layer_banner("6", "食谱优化")
            r = run_meal_eval(path)
            meal_th = thresholds.get("meal") if isinstance(thresholds.get("meal"), dict) else {}
            if "max_kcal_error_pct" in meal_th:
                r.max_kcal_error_pct = float(meal_th["max_kcal_error_pct"])
            if "max_protein_error_pct" in meal_th:
                r.max_protein_error_pct = float(meal_th["max_protein_error_pct"])
            if "min_pass_rate" in meal_th:
                r.min_pass_rate = float(meal_th["min_pass_rate"])
            report.layers.append(
                LayerReport(
                    layer="6",
                    title="食谱优化",
                    ok=r.ok,
                    summary=r.summary_text(),
                    metrics={"pass_rate": r.pass_rate, "cases": _cases_payload(r.cases)},
                )
            )

    # Layer 7 — safety
    if _mod_enabled("safety", True):
        path = _suite("safety", "evals/large/safety_cases.json")
        if path.exists():
            layer_banner("7", "安全与联合调整")
            r = run_safety_eval(path)
            report.layers.append(
                LayerReport(
                    layer="7",
                    title="安全与联合调整",
                    ok=r.ok,
                    summary=r.summary_text(),
                    metrics={"pass_rate": r.pass_rate, "cases": _cases_payload(r.cases)},
                )
            )

    # Layer 8 — context / KV / orchestration (offline)
    if _mod_enabled("context_kv", True):
        path = _suite("context_kv", "evals/large/context_kv_cases.json")
        if path.exists():
            layer_banner("8", "长上下文与编排")
            r = run_context_kv_eval(path)
            th = thresholds.get("context_kv") if isinstance(thresholds.get("context_kv"), dict) else {}
            if "min_reduction" in th:
                r.min_reduction = float(th["min_reduction"])
            if "min_recall_at_budget" in th:
                r.min_recall_at_budget = float(th["min_recall_at_budget"])
            if "min_lcp" in th:
                r.min_lcp = float(th["min_lcp"])
            if "min_route_accuracy" in th:
                r.min_route_accuracy = float(th["min_route_accuracy"])
            if "min_orchestrator_pass" in th:
                r.min_orchestrator_pass = float(th["min_orchestrator_pass"])
            # 阈值可能覆盖默认后需重算 ok
            r.ok = (
                r.avg_reduction >= r.min_reduction
                and r.avg_recall_at_budget >= r.min_recall_at_budget
                and r.avg_lcp >= r.min_lcp
                and r.route_accuracy >= r.min_route_accuracy
                and r.orchestrator_pass >= r.min_orchestrator_pass
                and all(c.ok for c in r.cases)
            )
            report.layers.append(
                LayerReport(
                    layer="8",
                    title="长上下文与编排",
                    ok=r.ok,
                    summary=r.summary_text(),
                    metrics={
                        "avg_reduction": r.avg_reduction,
                        "avg_recall_at_budget": r.avg_recall_at_budget,
                        "avg_lcp": r.avg_lcp,
                        "route_accuracy": r.route_accuracy,
                        "orchestrator_pass": r.orchestrator_pass,
                        "cases": _cases_payload(r.cases),
                    },
                )
            )

    report.ok = bool(report.layers) and all(l.ok for l in report.layers)

    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "ok": report.ok,
            "layers": [
                {
                    "layer": l.layer,
                    "title": l.title,
                    "ok": l.ok,
                    "summary": l.summary,
                    "metrics": l.metrics,
                }
                for l in report.layers
            ],
        }
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if md_path:
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(report.to_markdown(), encoding="utf-8")

    return report
