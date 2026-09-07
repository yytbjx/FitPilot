#!/usr/bin/env python3
"""裁剪 evals/large：保留优质题，去掉为凑整数而灌水的扩写。

原则：
  - 不推倒重来；在现有大集上 prune / 去重 / 分层封顶
  - 条数变为「自然数」（不规则），写入 suite_manifest
  - 小集 evals/fewshot 不动

用法（仓库根目录）：
  python scripts/prune_large_suites.py
  python scripts/prune_large_suites.py --dry-run
  python scripts/prune_large_suites.py --only golden_rag,meal,generation
"""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
LARGE = ROOT / "evals" / "large"
SEED = 20260725


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _norm_q(q: str) -> str:
    q = (q or "").strip().lower()
    q = re.sub(r"[\s？?。.!！，,、]+", "", q)
    return q


def _cap_by_key(
    cases: list[dict[str, Any]],
    key_fn: Callable[[dict[str, Any]], Any],
    *,
    max_per_key: int,
    rng: random.Random,
    prefer_fn: Callable[[dict[str, Any]], int] | None = None,
) -> list[dict[str, Any]]:
    buckets: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for c in cases:
        buckets[key_fn(c)].append(c)
    out: list[dict[str, Any]] = []
    for _, group in buckets.items():
        if prefer_fn:
            group = sorted(group, key=prefer_fn)
        else:
            rng.shuffle(group)
        out.extend(group[:max_per_key])
    # 稳定一点：按原 id 排序
    out.sort(key=lambda c: str(c.get("id") or ""))
    return out


def _prefer_origin(c: dict[str, Any]) -> int:
    """越小越优先保留。"""
    origin = str(c.get("origin") or "")
    diff = str(c.get("difficulty") or "")
    rank = {
        "fewshot": 0,
        "kb": 1,
        "fewshot_paraphrase": 2,
    }.get(origin, 5)
    if diff == "hard":
        rank += 0
    elif diff == "medium":
        rank += 1
    else:
        rank += 2
    return rank


def prune_golden_rag(data: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """KB 题已较好：每 expect_any 最多 3 条；fewshot 锚点全留。"""
    cases = list(data.get("cases") or [])
    seeds = [c for c in cases if c.get("origin") == "fewshot"]
    rest = [c for c in cases if c.get("origin") != "fewshot"]
    rest = _cap_by_key(
        rest,
        lambda c: tuple(c.get("expect_any") or []),
        max_per_key=3,
        rng=rng,
        prefer_fn=_prefer_origin,
    )
    # 同问句归一化去重
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for c in seeds + rest:
        nq = _norm_q(str(c.get("query") or ""))
        if nq in seen:
            continue
        seen.add(nq)
        deduped.append(c)
    data = dict(data)
    data["cases"] = deduped
    data["description"] = (
        (data.get("description") or "")
        + " [pruned: cap expect_any≤3, keep fewshot anchors]"
    ).strip()
    return data


def prune_golden_rag_offline(data: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """fixture 容量有限：每 expect_any ≤2，总量软上限 ~100。"""
    cases = list(data.get("cases") or [])
    # 优先保留无 _v 扩写后缀的种子味 id
    cases = _cap_by_key(
        cases,
        lambda c: tuple(c.get("expect_any") or []),
        max_per_key=4,
        rng=rng,
        prefer_fn=lambda c: (0 if "_v" not in str(c.get("id") or "") else 1, str(c.get("id"))),
    )
    if len(cases) > 80:
        rng.shuffle(cases)
        cases = sorted(cases[:80], key=lambda c: str(c.get("id") or ""))
    data = dict(data)
    data["cases"] = cases
    data["description"] = (
        "离线 RAG 大集（pruned）：按 expect_any 去重封顶，适配 fixture 容量。"
    )
    return data


def prune_generation(data: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """5→250 灌水最重：保留种子 + 每模式有限变体，目标约 60–80。"""
    cases = list(data.get("cases") or [])
    seed_ids = {
        str(c.get("id"))
        for c in cases
        if not re.search(r"_\d{3,}$", str(c.get("id") or ""))
    }
    seeds = [c for c in cases if str(c.get("id")) in seed_ids]
    expanded = [c for c in cases if str(c.get("id")) not in seed_ids]

    def mode_key(c: dict[str, Any]) -> str:
        return str(c.get("mode") or "static")

    # 种子全留；扩写按 mode 封顶
    expanded = _cap_by_key(
        expanded,
        mode_key,
        max_per_key=18,
        rng=rng,
        prefer_fn=lambda c: (0 if c.get("mode") == "e2e_retrieve" else 1, str(c.get("id"))),
    )
    # 再按 expect 关键词簇封顶
    expanded = _cap_by_key(
        expanded,
        lambda c: tuple(c.get("expect_citation_keywords") or c.get("expect_answer_contains") or [c.get("id")]),
        max_per_key=3,
        rng=rng,
    )
    out = seeds + expanded
    if len(out) > 80:
        # 保种子，裁扩写
        keep_exp = out[len(seeds) :]
        rng.shuffle(keep_exp)
        out = seeds + sorted(keep_exp[: max(0, 80 - len(seeds))], key=lambda c: str(c.get("id")))
    data = dict(data)
    data["cases"] = out
    data["description"] = "generation 大集（pruned）：去灌水扩写，保留种子与有限变体。"
    return data


def prune_generation_online(data: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    cases = list(data.get("cases") or [])
    cases = _cap_by_key(
        cases,
        lambda c: (c.get("mode"), tuple(c.get("expect_rubric") or []) or c.get("id")),
        max_per_key=2,
        rng=rng,
    )
    if len(cases) > 40:
        rng.shuffle(cases)
        cases = sorted(cases[:40], key=lambda c: str(c.get("id") or ""))
    data = dict(data)
    data["cases"] = cases
    return data


def prune_parsing(data: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """每 suffix 留有限条，总量约 72。"""
    cases = list(data.get("cases") or [])
    cases = _cap_by_key(
        cases,
        lambda c: str(c.get("suffix") or ".txt"),
        max_per_key=12,
        rng=rng,
        prefer_fn=lambda c: (0 if not str(c.get("id") or "").startswith("parse_") else 1, str(c.get("id"))),
    )
    data = dict(data)
    data["cases"] = cases
    data["description"] = "parsing 大集（pruned）：按格式封顶，去掉凑数变体。"
    return data


def prune_no_answer(data: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """正负大致保留，但同问句归一化去重 + 每标签封顶。"""
    cases = list(data.get("cases") or [])
    # 去重
    seen: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for c in cases:
        nq = _norm_q(str(c.get("query") or ""))
        if nq in seen:
            continue
        seen.add(nq)
        uniq.append(c)
    # 每标签最多 80
    pos = [c for c in uniq if c.get("expect_no_answer") is False]
    neg = [c for c in uniq if c.get("expect_no_answer") is True]
    other = [c for c in uniq if c.get("expect_no_answer") not in (True, False)]
    rng.shuffle(pos)
    rng.shuffle(neg)
    # 优先无扩写 id
    def seedish(cs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seeds = [c for c in cs if not re.search(r"_\d{3,}", str(c.get("id") or ""))]
        rest = [c for c in cs if c not in seeds]
        return seeds + rest

    pos = seedish(pos)[:80]
    neg = seedish(neg)[:80]
    out = sorted(pos + neg + other, key=lambda c: str(c.get("id") or ""))
    data = dict(data)
    data["cases"] = out
    data["description"] = "no_answer 大集（pruned）：去重并限制正负各 ≤80。"
    return data


def prune_plan(data: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """降低负例一边倒：模板去重后，负例不超过正例的 1.25 倍；总量软上限 ~160。"""
    cases = list(data.get("cases") or [])
    pos = [c for c in cases if c.get("expect_ok") is True]
    neg = [c for c in cases if c.get("expect_ok") is False]
    other = [c for c in cases if c.get("expect_ok") not in (True, False)]

    def plan_sig(c: dict[str, Any]) -> tuple:
        w = c.get("workout") or {}
        p = c.get("profile") or {}
        days = w.get("days") or []
        ex_names: list[str] = []
        for d in days:
            for ex in d.get("exercises") or []:
                ex_names.append(str(ex.get("name") or ""))
            if not (d.get("exercises") or []):
                ex_names.append("__empty__")
        return (
            bool(c.get("expect_ok")),
            int(w.get("weekly_sessions") or 0),
            int(p.get("weekly_sessions") or 0),
            str(p.get("experience_level") or ""),
            str(p.get("injuries") or "")[:20],
            tuple(ex_names[:8]),
            len(days),
        )

    pos = _cap_by_key(pos, plan_sig, max_per_key=3, rng=rng)
    neg = _cap_by_key(neg, plan_sig, max_per_key=4, rng=rng)
    max_neg = max(24, int(len(pos) * 1.25))
    if len(neg) > max_neg:
        # 优先保留种子味 id
        neg = sorted(
            neg,
            key=lambda c: (0 if not str(c.get("id") or "").startswith("plan_") else 1, str(c.get("id"))),
        )
        neg = neg[:max_neg]
    out = sorted(pos + neg + other, key=lambda c: str(c.get("id") or ""))
    if len(out) > 160:
        # 保正例，裁负例
        pos2 = [c for c in out if c.get("expect_ok") is True]
        neg2 = [c for c in out if c.get("expect_ok") is False]
        other2 = [c for c in out if c.get("expect_ok") not in (True, False)]
        budget = max(0, 160 - len(pos2) - len(other2))
        neg2 = neg2[:budget]
        out = sorted(pos2 + neg2 + other2, key=lambda c: str(c.get("id") or ""))
    data = dict(data)
    data["cases"] = out
    data["description"] = "plan 大集（pruned）：动作/课表签名去重，负例≤正例×1.25。"
    return data


def prune_safety(data: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    cases = list(data.get("cases") or [])
    cases = _cap_by_key(
        cases,
        lambda c: (
            c.get("kind"),
            c.get("expect_risk_level"),
            _norm_q(str(c.get("text") or c.get("query") or ""))[:24],
        ),
        max_per_key=2,
        rng=rng,
        prefer_fn=lambda c: (0 if not str(c.get("id") or "").startswith("safety_") else 1, str(c.get("id"))),
    )
    # soft cap
    if len(cases) > 120:
        # 保 high
        high = [c for c in cases if c.get("expect_risk_level") == "high"]
        rest = [c for c in cases if c not in high]
        rng.shuffle(rest)
        cases = sorted(high + rest[: max(0, 120 - len(high))], key=lambda c: str(c.get("id")))
    data = dict(data)
    data["cases"] = cases
    data["description"] = "safety 大集（pruned）：按 kind/level/文本去重封顶。"
    return data


def prune_agent(data: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """意图已均衡：仅去重 message，基本全留。"""
    _ = rng
    cases = list(data.get("cases") or [])
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for c in cases:
        nq = _norm_q(str(c.get("message") or ""))
        if nq in seen:
            continue
        seen.add(nq)
        out.append(c)
    data = dict(data)
    data["cases"] = out
    data["description"] = (
        data.get("description") or "agent 大集"
    ) + " [pruned: dedupe messages]"
    return data


def prune_meal(data: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """负例全留；正例按目标簇×食物签名封顶，去掉高度重复。"""
    cases = list(data.get("cases") or [])
    neg = [c for c in cases if c.get("expect_ok") is False]
    pos = [c for c in cases if c.get("expect_ok") is not False]

    def meal_key(c: dict[str, Any]) -> tuple:
        t = c.get("targets") or {}
        foods = tuple(sorted(str(f.get("name") or "") for f in (c.get("foods") or [])))
        return (
            round(float(t.get("kcal") or 0) / 100) * 100,
            round(float(t.get("protein_g") or 0) / 10) * 10,
            bool(c.get("use_ortools", True)),
            foods,
        )

    pos = _cap_by_key(
        pos,
        meal_key,
        max_per_key=2,
        rng=rng,
        prefer_fn=lambda c: (0 if c.get("use_ortools") else 1, -len(c.get("foods") or []), str(c.get("id"))),
    )
    # soft upper bound ~180 pos
    if len(pos) > 180:
        rng.shuffle(pos)
        pos = sorted(pos[:180], key=lambda c: str(c.get("id") or ""))
    out = sorted(pos + neg, key=lambda c: str(c.get("id") or ""))
    data = dict(data)
    data["cases"] = out
    data["description"] = (
        "meal 大集（pruned）：负例保留；正例按目标×食物集封顶，去掉凑数重复。"
        "（可行性 OR-Tools 校验仍建议评测期/后续脚本做）"
    )
    return data


PRUNERS: dict[str, Callable[[dict[str, Any], random.Random], dict[str, Any]]] = {
    "golden_rag.json": prune_golden_rag,
    "golden_rag_offline.json": prune_golden_rag_offline,
    "generation_cases.json": prune_generation,
    "generation_online_cases.json": prune_generation_online,
    "parsing_cases.json": prune_parsing,
    "no_answer_cases.json": prune_no_answer,
    "plan_cases.json": prune_plan,
    "safety_cases.json": prune_safety,
    "agent_routing_cases.json": prune_agent,
    "meal_cases.json": prune_meal,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="裁剪 large 评测集（保留优质题）")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", default="", help="逗号分隔文件名或别名")
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    rng = random.Random(args.seed)

    only = {x.strip() for x in args.only.split(",") if x.strip()}
    aliases = {
        "golden_rag": "golden_rag.json",
        "retrieval": "golden_rag.json",
        "offline": "golden_rag_offline.json",
        "golden_rag_offline": "golden_rag_offline.json",
        "generation": "generation_cases.json",
        "generation_online": "generation_online_cases.json",
        "parsing": "parsing_cases.json",
        "no_answer": "no_answer_cases.json",
        "plan": "plan_cases.json",
        "safety": "safety_cases.json",
        "agent": "agent_routing_cases.json",
        "meal": "meal_cases.json",
    }
    selected = set(PRUNERS.keys())
    if only:
        selected = set()
        for x in only:
            selected.add(aliases.get(x, x if x.endswith(".json") else f"{x}_cases.json"))

    before: dict[str, int] = {}
    after: dict[str, int] = {}
    print(f"{'DRY-RUN ' if args.dry_run else ''}pruning evals/large ...")
    for name, pruner in PRUNERS.items():
        if name not in selected:
            continue
        path = LARGE / name
        if not path.exists():
            print(f"  skip missing {name}")
            continue
        data = _load(path)
        n0 = len(data.get("cases") or [])
        pruned = pruner(data, random.Random(args.seed + hash(name) % 10000))
        n1 = len(pruned.get("cases") or [])
        before[name] = n0
        after[name] = n1
        print(f"  {name}: {n0} -> {n1} ({n1 - n0:+d})")
        if not args.dry_run:
            _dump(path, pruned)

    # 未裁剪的文件也记入 manifest written
    written = dict(after)
    for p in LARGE.glob("*.json"):
        if p.name == "suite_manifest.json":
            continue
        if p.name not in written:
            try:
                written[p.name] = len(_load(p).get("cases") or [])
            except Exception:  # noqa: BLE001
                pass

    meta = {
        "suite_set": "large",
        "mode": "capacity_pruned",
        "seed": args.seed,
        "policy": "retain_and_prune",
        "notes": (
            "条数按去重/主题封顶自然形成，不再凑 200/250/300；"
            "由 scripts/prune_large_suites.py 在现有 large 上裁剪保留。"
        ),
        "before": before,
        "written": written,
        "total_cases": sum(written.values()),
        "large_suite_dir": "evals/large",
        "small_suite_dir": "evals/fewshot",
    }
    if not args.dry_run:
        prev_path = LARGE / "suite_manifest.json"
        if prev_path.exists():
            try:
                old = _load(prev_path)
                meta["previous_notes"] = old.get("notes")
                meta["sizes_legacy_quotas"] = old.get("sizes")
            except Exception:  # noqa: BLE001
                pass
        _dump(prev_path, meta)
        (LARGE / "README.md").write_text(
            "# 大评测总集（large）\n\n"
            "容量驱动：**有多少（去重后）留多少**，不再为凑整数灌水。\n\n"
            "- 生成：`scripts/generate_large_eval_suites.py` / "
            "`scripts/generate_rag_suite_from_kb.py`\n"
            "- 裁剪保留：`scripts/prune_large_suites.py`（推荐在扩写或 KB 出题后跑）\n"
            "- 小集 `evals/fewshot` 不裁剪\n\n"
            "实际条数见 `suite_manifest.json`。\n",
            encoding="utf-8",
        )
        print(f"wrote suite_manifest.json total_cases={meta['total_cases']}")
    else:
        print(f"dry-run total would be ~{sum(after.values())} (pruned files only)")


if __name__ == "__main__":
    main()
