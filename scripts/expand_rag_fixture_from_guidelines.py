#!/usr/bin/env python3
"""从已下载的真实 guidelines Markdown 抽取段落，扩充 evals/rag_fixture（不捏造）。"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "knowledge_base" / "raw" / "curated" / "guidelines"
FIXTURE = ROOT / "evals" / "rag_fixture"

# 主题 → 匹配关键词（用于挑选段落）与输出文件名
TOPICS: list[tuple[str, str, list[str]]] = [
    ("who_pa_adults_fixture.md", "WHO 身体活动（事实清单摘录）", ["150", "300", "肌肉", "身体活动", "久坐"]),
    ("who_healthy_diet_fixture.md", "WHO 健康饮食（事实清单摘录）", ["水果", "蔬菜", "盐", "糖", "脂肪", "健康饮食"]),
    ("who_salt_fixture.md", "WHO 减盐（事实清单摘录）", ["盐", "5", "钠", "血压"]),
    ("cn_diet_eight_fixture.md", "中国居民膳食指南八准则（官网摘录）", ["准则", "食物多样", "控糖", "饮水", "蔬果"]),
    ("cn_fitness_guide_fixture.md", "全民健身指南解读（体育总局摘录）", ["健身", "运动", "体质", "体育活动"]),
    ("obesity_activity_fixture.md", "超重肥胖与身体活动（WHO 摘录）", ["肥胖", "超重", "体重", "身体活动"]),
    ("hypertension_lifestyle_fixture.md", "高血压相关生活方式（WHO 摘录，非诊疗）", ["血压", "盐", "身体活动", "150"]),
    ("hydration_water_fixture.md", "饮水与补水（CDC/NHS 等公开摘录）", ["water", "饮", "水", "dehydr", "尿", "fluid"]),
    ("weight_management_fixture.md", "体重管理基础（CDC/NHS 公开摘录，非医疗处方）", ["weight", "体重", "calorie", "热量", "lose"]),
    ("strength_flexibility_fixture.md", "力量与柔韧（NHS/CDC 公开摘录）", ["strength", "力量", "flexib", "muscle", "肌肉"]),
    ("children_pa_fixture.md", "儿童青少年身体活动（WHO/CDC 公开摘录）", ["儿童", "青少年", "60", "屏幕"]),
    ("added_sugar_fixture.md", "添加糖（CDC/WHO/NHS 公开摘录）", ["sugar", "糖", "added", "beverage", "饮料", "free sugar"]),
    ("cvd_lifestyle_fixture.md", "心血管健康生活方式（WHO 摘录，非诊疗）", ["心脏", "心血管", "血压", "身体活动", "烟草", "盐"]),
    ("malnutrition_fixture.md", "营养不良相关公开科普（WHO 摘录）", ["营养", "消瘦", "超重", "微量", "母乳"]),
    ("salt_nhs_fixture.md", "减盐实践（NHS/WHO 公开摘录）", ["salt", "钠", "sodium", "盐", "血压"]),
]


def paras(text: str) -> list[str]:
    parts = re.split(r"\n{2,}", text)
    out = []
    for p in parts:
        p = p.strip()
        if len(p) < 40:
            continue
        if p.startswith(">"):
            continue
        if p.startswith("#"):
            # keep heading+following short
            continue
        out.append(p)
    return out


def main() -> None:
    FIXTURE.mkdir(parents=True, exist_ok=True)
    corpus: list[tuple[Path, str]] = []
    for p in sorted(GUIDE.glob("*.md")):
        corpus.append((p, p.read_text(encoding="utf-8")))

    existing_hashes = {
        hashlib.sha256(p.read_bytes()).hexdigest() for p in FIXTURE.glob("*.md")
    }

    for fname, title, keys in TOPICS:
        chosen: list[str] = []
        sources: list[str] = []
        for path, text in corpus:
            score_paras = []
            for para in paras(text):
                score = sum(1 for k in keys if k in para)
                if score >= 1:
                    score_paras.append((score, para))
            score_paras.sort(key=lambda x: (-x[0], -len(x[1])))
            for score, para in score_paras[:3]:
                if para in chosen:
                    continue
                chosen.append(para)
                # 找来源行
                m = re.search(r"> 来源[^：:]*[：:]\s*(\S+)", text)
                sources.append(m.group(1) if m else path.name)
            if len(chosen) >= 6:
                break
        if len(chosen) < 2:
            print(f"SKIP insufficient {fname}")
            continue
        body = [f"# {title}", ""]
        body.append("> 本文件段落摘录自 knowledge_base/raw/curated/guidelines 已下载公开原文，未改写事实。")
        body.append("")
        if sources:
            body.append("> 来源示例：" + "；".join(dict.fromkeys(sources))[:500])
            body.append("")
        for i, para in enumerate(chosen[:8], 1):
            body.append(f"## 摘录 {i}")
            body.append("")
            body.append(para)
            body.append("")
        content = "\n".join(body)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if digest in existing_hashes:
            print(f"DUP {fname}")
            continue
        out = FIXTURE / fname
        out.write_text(content, encoding="utf-8")
        existing_hashes.add(digest)
        print(f"WRITE {out.name} paras={min(8, len(chosen))} chars={len(content)}")


if __name__ == "__main__":
    main()
