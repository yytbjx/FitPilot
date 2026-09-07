#!/usr/bin/env python3
"""评估知识库主题覆盖是否足以支撑 200–500 条检索评测样本。"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BM25 = ROOT / "knowledge_base" / "bm25_index.json"
FIXTURE = ROOT / "evals" / "rag_fixture"
GOLDEN = ROOT / "evals" / "fewshot" / "golden_rag.json"
if not GOLDEN.exists():
    GOLDEN = ROOT / "evals" / "golden_rag.json"

# 评测可独立出题的主题簇（每簇期望可支撑约 20–40 条不重复问法）
THEME_KEYS: dict[str, list[str]] = {
    "protein": ["蛋白", "1.6", "2.2", "鸡胸"],
    "who_pa": ["150", "300", "身体活动", "久坐"],
    "cn_diet": ["膳食", "准则", "食物多样", "控糖"],
    "fat_loss_myth": ["减脂", "主食", "误区", "有氧", "体重", "热量"],
    "hydration": ["饮水", "电解质", "运动饮料", "出汗", "water", "脱水", "尿"],
    "strength": ["力量", "渐进", "超负荷", "2", "3"],
    "safety": ["诊断", "开药", "胸痛", "就医"],
    "salt": ["盐", "钠", "5g", "减盐"],
    "healthy_diet": ["蔬果", "全谷", "奶", "脂肪"],
    "obesity": ["肥胖", "超重", "体重"],
    "usda_food": ["kcal", "鹰嘴豆", "西兰花", "酸奶", "USDA"],
    "fitness_guide": ["全民健身", "体质", "科学健身", "健身指南", "体育活动", "运动处方", "健身"],
    "children_pa": ["儿童", "青少年", "60", "每天", "屏幕"],
    "older_pa": ["老年", "平衡", "跌倒", "力量"],
    "weight_mgmt": ["减重", "体重管理", "热量", "weight", "calorie"],
    "added_sugar": ["添加糖", "含糖饮料", "sugar", "糖"],
}


def main() -> None:
    docs: list[str] = []
    if BM25.exists():
        data = json.loads(BM25.read_text(encoding="utf-8"))
        payloads = data.get("payloads") or {}
        if isinstance(payloads, dict) and payloads:
            docs = [str((v or {}).get("text") or "") for v in payloads.values()]
        else:
            raw_docs = list(data.get("docs") or [])
            docs = ["".join(x) if isinstance(x, list) else str(x) for x in raw_docs]
        print(f"bm25_chunks={len(docs)}")
    else:
        print("bm25 missing")

    blob = "\n".join(docs).lower()
    # also fixture
    fix_texts = []
    for p in FIXTURE.glob("*.md"):
        fix_texts.append(p.read_text(encoding="utf-8"))
    fix_blob = "\n".join(fix_texts)

    covered = []
    weak = []
    for theme, keys in THEME_KEYS.items():
        hits = sum(1 for k in keys if k.lower() in blob)
        fix_hits = sum(1 for k in keys if k in fix_blob)
        # 主题可出题容量粗估：命中关键词越多、相关段落越多，容量越高
        para_hits = sum(1 for d in docs if any(k.lower() in d.lower() for k in keys))
        capacity = min(60, max(0, para_hits // 3 + hits * 5))
        row = {
            "theme": theme,
            "key_hits": hits,
            "fixture_key_hits": fix_hits,
            "doc_paras": para_hits,
            "est_cases": capacity,
        }
        if capacity >= 25 and hits >= 2:
            covered.append(row)
        else:
            weak.append(row)
        print(
            f"{theme:16} keys={hits}/{len(keys)} fixture={fix_hits} "
            f"paras≈{para_hits} est_cases≈{capacity}"
        )

    total_est = sum(r["est_cases"] for r in covered) + sum(r["est_cases"] for r in weak)
    strong_est = sum(r["est_cases"] for r in covered)
    print("---")
    print(f"strong_themes={len(covered)}/{len(THEME_KEYS)} strong_est_cases≈{strong_est}")
    print(f"all_themes_est_cases≈{total_est}")
    print(f"fixture_files={len(list(FIXTURE.glob('*.md')))}")
    # verdict
    if strong_est >= 200:
        print("VERDICT: CAN_SUPPORT_200_PLUS (strong themes alone)")
    elif total_est >= 200:
        print("VERDICT: MARGINAL_200 (need weak themes / paraphrases)")
    else:
        print("VERDICT: INSUFFICIENT_FOR_200")

    if GOLDEN.exists():
        g = json.loads(GOLDEN.read_text(encoding="utf-8"))
        print(f"golden_seed_cases={len(g.get('cases') or [])}")


if __name__ == "__main__":
    main()
