"""多层评估统一编排（解析 / 检索 / 拒答 / 生成 / Agent / 计划 / 食谱 / 安全）。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.eval.agent_eval import run_agent_eval
from app.eval.generation_eval import run_generation_eval
from app.eval.generation_online_eval import run_generation_online_eval
from app.eval.meal_eval import run_meal_eval
from app.eval.no_answer_eval import run_no_answer_eval
from app.eval.parsing_eval import run_parsing_eval
from app.eval.plan_eval import run_plan_eval
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
) -> FullEvalReport:
    root = repo_root or config_path.parent.parent
    cfg = _load_config(config_path)
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
        path = _suite("parsing", "evals/parsing_cases.json")
        if path.exists():
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
        suite = _suite("retrieval", params.get("dataset_path") or "evals/golden_rag.json")
        if suite.exists():
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
                        "cases": _cases_payload(r.cases),
                    },
                )
            )

    # Layer 2b — no_answer
    if _mod_enabled("no_answer", True):
        path = _suite("no_answer", "evals/no_answer_cases.json")
        if path.exists():
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
        path = _suite("generation", "evals/generation_cases.json")
        if path.exists():
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
        path = _suite("generation_online", "evals/generation_online_cases.json")
        if path.exists():
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
        path = _suite("agent", "evals/agent_routing_cases.json")
        if path.exists():
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
        path = _suite("plan", "evals/plan_cases.json")
        if path.exists():
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
        path = _suite("meal", "evals/meal_cases.json")
        if path.exists():
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
        path = _suite("safety", "evals/safety_cases.json")
        if path.exists():
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
