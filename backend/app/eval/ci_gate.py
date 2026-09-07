"""CI 离线评测门禁：不依赖 Qdrant/Ollama/Embedding 模型的层。

迭代 3 新增 retrieval_offline / no_answer_offline：基于 evals/rag_fixture
固定语料 + 确定性哈希向量 + 真实 BM25/RRF/build_context 路径，确定性通过/失败。
配置唯一权威：evals/eval_config.yaml（JSON 版已删除）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.eval.agent_eval import run_agent_eval
from app.eval.context_kv_eval import run_context_kv_eval
from app.eval.meal_eval import run_meal_eval
from app.eval.offline_rag_eval import OfflineRagEvalResult, run_offline_rag_eval
from app.eval.parsing_eval import run_parsing_eval
from app.eval.plan_eval import run_plan_eval
from app.eval.progress import layer_banner
from app.eval.rag_eval import load_eval_config
from app.eval.safety_eval import run_safety_eval

# 仅离线可跑的模块（在线 retrieval / generation e2e / no_answer 依赖索引，排除；
# 离线检索层 retrieval_offline / no_answer_offline 在 CI 中确定性地覆盖 RAG 检索与拒答）
OFFLINE_LAYERS = (
    "parsing",
    "retrieval_offline",
    "no_answer_offline",
    "agent",
    "plan",
    "meal",
    "safety",
    "context_kv",
)


@dataclass
class GateLayerResult:
    layer: str
    ok: bool
    summary: str
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class CiGateReport:
    layers: list[GateLayerResult] = field(default_factory=list)
    ok: bool = False
    config_path: str = ""

    def summary_text(self) -> str:
        lines = ["=== FitPilot CI Offline Gates ==="]
        for lr in self.layers:
            mark = "PASS" if lr.ok else "FAIL"
            lines.append(f"[{mark}] {lr.layer}: {lr.summary}")
        lines.append(f"overall={'PASS' if self.ok else 'FAIL'}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "config_path": self.config_path,
            "layers": [
                {"layer": x.layer, "ok": x.ok, "summary": x.summary, "metrics": x.metrics}
                for x in self.layers
            ],
        }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def run_ci_gates(
    config_path: Path | None = None,
    *,
    suite_set: str | None = None,
) -> CiGateReport:
    """按 eval_config 阈值跑离线层；任一失败则 overall FAIL。"""
    root = _repo_root()
    cfg_path = config_path or (root / "evals" / "eval_config.yaml")
    cfg = load_eval_config(cfg_path) if cfg_path.exists() else {}
    if suite_set:
        from app.eval.suite_set import apply_suite_set_to_config

        cfg = apply_suite_set_to_config(cfg, repo_root=root, suite_set=suite_set)
    suites = cfg.get("suites") or {}
    thresholds = cfg.get("thresholds") or {}
    modules = cfg.get("modules") or {}

    report = CiGateReport(config_path=str(cfg_path))

    # 离线检索层只跑一次，retrieval_offline / no_answer_offline 共享结果
    offline_rag: OfflineRagEvalResult | None = None
    offline_rag_error: str | None = None

    def _run_offline_rag(suite: Path) -> OfflineRagEvalResult | None:
        nonlocal offline_rag, offline_rag_error
        if offline_rag is not None or offline_rag_error is not None:
            return offline_rag
        try:
            params = cfg.get("parameters") or {}
            fixture = params.get("offline_fixture_dir") or "evals/rag_fixture"
            fixture_path = Path(fixture)
            if not fixture_path.is_absolute():
                fixture_path = root / fixture
            offline_rag = run_offline_rag_eval(
                fixture_path,
                suite,
                k_list=list(params.get("top_k_list") or [1, 3, 5]),
            )
        except Exception as exc:  # noqa: BLE001
            offline_rag_error = str(exc)
        return offline_rag

    for layer in OFFLINE_LAYERS:
        mod = modules.get(layer) or {}
        if mod.get("enabled") is False:
            continue
        rel = suites.get(layer)
        if not rel:
            continue
        path = root / rel if not Path(rel).is_absolute() else Path(rel)
        if not path.exists():
            report.layers.append(
                GateLayerResult(layer=layer, ok=False, summary=f"suite missing: {path}")
            )
            continue

        th = thresholds.get(layer) or {}
        layer_banner(layer, layer)
        if layer == "agent":
            r = run_agent_eval(path)
            if "min_accuracy" in th:
                r.min_accuracy = float(th["min_accuracy"])
            if "min_macro_f1" in th:
                r.min_macro_f1 = float(th["min_macro_f1"])
            report.layers.append(
                GateLayerResult(
                    layer=layer,
                    ok=r.ok,
                    summary=r.summary_text(),
                    metrics={"accuracy": r.accuracy, "macro_f1": r.macro_f1},
                )
            )
        elif layer == "plan":
            r = run_plan_eval(path)
            if "min_pass_rate" in th:
                r.min_pass_rate = float(th["min_pass_rate"])
            report.layers.append(
                GateLayerResult(
                    layer=layer,
                    ok=r.ok,
                    summary=r.summary_text(),
                    metrics={"pass_rate": r.pass_rate},
                )
            )
        elif layer == "meal":
            r = run_meal_eval(path)
            if "min_pass_rate" in th:
                r.min_pass_rate = float(th["min_pass_rate"])
            report.layers.append(
                GateLayerResult(
                    layer=layer,
                    ok=r.ok,
                    summary=r.summary_text(),
                    metrics={"pass_rate": r.pass_rate},
                )
            )
        elif layer == "safety":
            r = run_safety_eval(path)
            if "min_pass_rate" in th:
                r.min_pass_rate = float(th["min_pass_rate"])
            report.layers.append(
                GateLayerResult(
                    layer=layer,
                    ok=r.ok,
                    summary=r.summary_text(),
                    metrics={"pass_rate": r.pass_rate},
                )
            )
        elif layer == "parsing":
            r = run_parsing_eval(path)
            if "min_pass_rate" in th:
                r.min_pass_rate = float(th["min_pass_rate"])
            report.layers.append(
                GateLayerResult(
                    layer=layer,
                    ok=r.ok,
                    summary=r.summary_text(),
                    metrics={"pass_rate": r.pass_rate},
                )
            )
        elif layer == "retrieval_offline":
            r = _run_offline_rag(path)
            if r is None:
                report.layers.append(
                    GateLayerResult(
                        layer=layer, ok=False, summary=f"offline rag eval failed: {offline_rag_error}"
                    )
                )
                continue
            min_hit = float(th.get("hit_rate", 0.7))
            min_mrr = float(th.get("mrr", 0.3))
            min_precision_at_5 = float(th.get("precision_at_5", 0.0) or 0.0)
            min_term_recall_at_5 = float(th.get("term_recall_at_5", 0.0) or 0.0)
            ok = (
                r.retrieval_cases > 0
                and r.hit_rate >= min_hit
                and r.mrr >= min_mrr
            )
            if min_precision_at_5 > 0:
                ok = ok and r.precision_at_k.get("precision@5", 0.0) >= min_precision_at_5
            if min_term_recall_at_5 > 0:
                ok = ok and r.term_recall_at_k.get("term_recall@5", 0.0) >= min_term_recall_at_5
            report.layers.append(
                GateLayerResult(
                    layer=layer,
                    ok=ok,
                    summary=(
                        f"Offline Retrieval: hit_rate={r.hit_rate:.2%}(>={min_hit:.0%}) "
                        f"mrr={r.mrr:.4f}(>={min_mrr}) "
                        f"precision@5={r.precision_at_k.get('precision@5', 0.0):.4f} "
                        f"term_recall@5={r.term_recall_at_k.get('term_recall@5', 0.0):.4f} "
                        f"{'PASS' if ok else 'FAIL'}"
                    ),
                    metrics={
                        "hit_rate": r.hit_rate,
                        "mrr": r.mrr,
                        "hit_at_k": r.hit_at_k,
                        "ndcg_at_k": r.ndcg_at_k,
                        "precision_at_k": r.precision_at_k,
                        "term_recall_at_k": r.term_recall_at_k,
                        "anchor_chunk_at_k": r.anchor_chunk_at_k,
                        "anchor_doc_at_k": r.anchor_doc_at_k,
                        "anchor_chunk_cases": r.anchor_chunk_cases,
                        "anchor_doc_cases": r.anchor_doc_cases,
                    },
                )
            )
        elif layer == "no_answer_offline":
            r = _run_offline_rag(path)
            if r is None:
                report.layers.append(
                    GateLayerResult(
                        layer=layer, ok=False, summary=f"offline rag eval failed: {offline_rag_error}"
                    )
                )
                continue
            min_recall = float(th.get("min_no_answer_recall", 0.7))
            min_precision = float(th.get("min_no_answer_precision", 0.6))
            ok = (
                r.no_answer_total > 0
                and r.no_answer_recall >= min_recall
                and r.no_answer_precision >= min_precision
            )
            report.layers.append(
                GateLayerResult(
                    layer=layer,
                    ok=ok,
                    summary=(
                        f"Offline No-Answer: recall={r.no_answer_recall:.2%}(>={min_recall:.0%}) "
                        f"precision={r.no_answer_precision:.2%}(>={min_precision:.0%}) "
                        f"{'PASS' if ok else 'FAIL'}"
                    ),
                    metrics={
                        "no_answer_recall": r.no_answer_recall,
                        "no_answer_precision": r.no_answer_precision,
                    },
                )
            )
        elif layer == "context_kv":
            r = run_context_kv_eval(path)
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
            r.ok = (
                r.avg_reduction >= r.min_reduction
                and r.avg_recall_at_budget >= r.min_recall_at_budget
                and r.avg_lcp >= r.min_lcp
                and r.route_accuracy >= r.min_route_accuracy
                and r.orchestrator_pass >= r.min_orchestrator_pass
                and all(c.ok for c in r.cases)
            )
            report.layers.append(
                GateLayerResult(
                    layer=layer,
                    ok=r.ok,
                    summary=r.summary_text(),
                    metrics={
                        "avg_reduction": r.avg_reduction,
                        "avg_recall_at_budget": r.avg_recall_at_budget,
                        "avg_lcp": r.avg_lcp,
                        "route_accuracy": r.route_accuracy,
                        "orchestrator_pass": r.orchestrator_pass,
                    },
                )
            )

    report.ok = bool(report.layers) and all(x.ok for x in report.layers)
    return report
