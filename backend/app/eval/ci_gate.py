"""CI 离线评测门禁：不依赖 Qdrant/Ollama 的层。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.eval.agent_eval import run_agent_eval
from app.eval.meal_eval import run_meal_eval
from app.eval.parsing_eval import run_parsing_eval
from app.eval.plan_eval import run_plan_eval
from app.eval.safety_eval import run_safety_eval

# 仅离线可跑的模块（retrieval / generation e2e / no_answer 依赖索引，排除）
OFFLINE_LAYERS = ("parsing", "agent", "plan", "meal", "safety")


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


def run_ci_gates(config_path: Path | None = None) -> CiGateReport:
    """按 eval_config 阈值跑离线层；任一失败则 overall FAIL。"""
    root = _repo_root()
    cfg_path = config_path or (root / "evals" / "eval_config.json")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    suites = cfg.get("suites") or {}
    thresholds = cfg.get("thresholds") or {}
    modules = cfg.get("modules") or {}

    report = CiGateReport(config_path=str(cfg_path))

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

    report.ok = bool(report.layers) and all(x.ok for x in report.layers)
    return report
