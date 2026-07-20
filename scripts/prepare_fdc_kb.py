# -*- coding: utf-8 -*-
"""把 FDC 中文翻译包中的有用资料整理到 knowledge_base，并生成精简宏量 JSON。"""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

SRC = Path(r"D:/FitPilot/例子或数据/FoodData_Central_foundation_food_2026-04-30_中文翻译包")
DST = Path(r"D:/FitPilot/knowledge_base/raw/curated/fdc")
DST.mkdir(parents=True, exist_ok=True)

COPY_FILES = [
    "食品基础信息_中英对照.csv",
    "营养素名称_中英对照.csv",
    "食品份量_中英对照.csv",
    "翻译处理报告.json",
]


def _norm_header(h: str) -> str:
    return (h or "").replace("\ufeff", "").strip()


def load_summary_rows() -> list[dict]:
    path = SRC / "食品基础信息_中英对照.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        field_map = {_norm_header(k): k for k in (reader.fieldnames or [])}

        def g(row: dict, *candidates: str) -> str:
            for c in candidates:
                key = field_map.get(c) or c
                if key in row and row[key] not in (None, ""):
                    return str(row[key]).strip()
            # fuzzy: match by substring
            for want in candidates:
                for fk, orig in field_map.items():
                    if want in fk and row.get(orig) not in (None, ""):
                        return str(row[orig]).strip()
            return ""

        out = []
        for row in reader:
            fdc = g(row, "fdcId")
            if not fdc:
                continue
            item = {
                "fdcId": fdc,
                "ndbNumber": g(row, "ndbNumber"),
                "name_en": g(row, "食品英文名"),
                "name_zh": g(row, "食品中文名"),
                "category_en": g(row, "分类英文"),
                "category_zh": g(row, "分类中文"),
                "kcal_per_100g": _float(g(row, "能量_kcal_每100g")),
                "protein_g_per_100g": _float(g(row, "蛋白质_g_每100g")),
                "fat_g_per_100g": _float(g(row, "脂肪_g_每100g")),
                "carb_g_per_100g": _float(g(row, "碳水化合物_g_每100g")),
                "fiber_g_per_100g": _float(g(row, "膳食纤维_g_每100g")),
                "sugar_g_per_100g": _float(g(row, "总糖_g_每100g")),
                "sodium_mg_per_100g": _float(g(row, "钠_mg_每100g")),
            }
            out.append(item)
        return out


def _float(v: str) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def write_macros_json(rows: list[dict]) -> Path:
    path = DST / "foundation_foods_macros_zh.json"
    path.write_text(
        json.dumps(
            {
                "source": "USDA FoodData Central Foundation Foods 2026-04-30 + 中文翻译包",
                "count": len(rows),
                "unit": "per 100g",
                "items": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def write_rag_md(rows: list[dict]) -> Path:
    # Keep RAG lean: category overview + example macros, not all 363 inline
    by_cat: dict[str, list[dict]] = {}
    for r in rows:
        cat = r.get("category_zh") or r.get("category_en") or "未分类"
        by_cat.setdefault(cat, []).append(r)

    lines = [
        "# USDA 基础食品（Foundation Foods）中文宏量摘要",
        "",
        "> 来源：USDA FoodData Central Foundation Foods（2026-04-30）及本仓库中文翻译包。",
        "> 数值单位：每 100g。完整条目见 `foundation_foods_macros_zh.json` 与 Postgres `food_items`。",
        "",
        "## 使用说明",
        "",
        "- FitPilot 饮食计算使用蛋白/碳水/脂肪/热量；本摘要供知识问答引用。",
        "- 不构成医疗营养处方；慢病个体请遵医嘱。",
        "",
        f"## 收录规模：{len(rows)} 种基础食品，{len(by_cat)} 个分类",
        "",
    ]
    for cat, items in sorted(by_cat.items(), key=lambda x: (-len(x[1]), x[0])):
        lines.append(f"### {cat}（{len(items)}）")
        lines.append("")
        for r in items[:8]:
            name = r.get("name_zh") or r.get("name_en")
            en = r.get("name_en") or ""
            kcal = r.get("kcal_per_100g")
            p = r.get("protein_g_per_100g")
            c = r.get("carb_g_per_100g")
            f = r.get("fat_g_per_100g")
            lines.append(
                f"- **{name}**（{en}）：{kcal} kcal，蛋白 {p}g，碳水 {c}g，脂肪 {f}g"
            )
        if len(items) > 8:
            lines.append(f"- …另有 {len(items) - 8} 种，详见食物库检索")
        lines.append("")

    path = DST / "usda_foundation_foods_macros_zh.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> None:
    for name in COPY_FILES:
        src = SRC / name
        if not src.exists():
            print("missing", name)
            continue
        dst = DST / name
        shutil.copy2(src, dst)
        print("copied", name, "->", dst)

    rows = load_summary_rows()
    j = write_macros_json(rows)
    m = write_rag_md(rows)
    print("macros_json", j, "count", len(rows))
    print("rag_md", m)


if __name__ == "__main__":
    main()
