#!/usr/bin/env python3
"""从当前 knowledge_base（BM25 payloads）生成 RAG 黄金评测集。

设计原则（与 fewshot 一致，规模更大）：
  - 每题锚定真实 chunk：expect_any 必须出现在源 chunk 文本中
  - 按主题分层抽样，限制单文档/单主题膨胀
  - 难度配额：easy / medium / hard（hard 近义改写，削弱问句字面泄漏）
  - 可并入 fewshot 种子作锚点；每锚点最多少量 hard 改写

用法（仓库根目录）：
  python scripts/generate_rag_suite_from_kb.py
  python scripts/generate_rag_suite_from_kb.py --target 300 --out evals/large/golden_rag.json
"""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BM25 = ROOT / "knowledge_base" / "bm25_index.json"
FEWSHOT = ROOT / "evals" / "fewshot" / "golden_rag.json"
DEFAULT_OUT = ROOT / "evals" / "large" / "golden_rag.json"
SEED = 20260725

# 主题 → 匹配关键词（用于 chunk 归类；出题后再校验 expect 落在文本内）
THEME_KEYS: dict[str, list[str]] = {
    "protein": ["蛋白", "1.6", "2.2", "g/kg", "鸡胸", "鸡蛋", "大豆", "鱼虾"],
    "who_pa": ["150", "300", "身体活动", "久坐", "中等强度", "有氧", "75"],
    "cn_diet": ["膳食", "准则", "食物多样", "控糖", "少盐少油", "会烹会选", "谷薯"],
    "fat_loss_myth": ["减脂", "主食", "误区", "热量缺口", "有氧", "碳水", "回弹"],
    "hydration": ["饮水", "电解质", "运动饮料", "出汗", "脱水", "补水", "尿色"],
    "strength": ["力量", "渐进", "超负荷", "抗阻", "分化", "深蹲", "硬拉", "卧推", "组数"],
    "safety": ["诊断", "开药", "胸痛", "就医", "锐痛", "眩晕", "处方", "安全边界"],
    "salt": ["盐", "钠", "5g", "减盐", "少盐", "食盐"],
    "healthy_diet": ["蔬果", "全谷", "平衡膳食", "奶类", "脂肪", "膳食纤维", "多样化"],
    "obesity": ["肥胖", "超重", "体重管理", "减重", "BMI"],
    "usda_food": ["kcal", "USDA", "foundation", "宏量", "每100", "蛋白", "碳水"],
    "fitness_guide": ["全民健身", "科学健身", "健身指南", "体质", "健身", "体育活动"],
    "children_pa": ["儿童", "青少年", "60", "屏幕", "学龄"],
    "older_pa": ["老年", "平衡", "跌倒", "多组分", "高龄"],
    "weight_mgmt": ["减重", "热量", "体重管理", "calorie", "能量摄入"],
    "added_sugar": ["添加糖", "含糖饮料", "糖", "sugar", "游离糖"],
}

# 主题问法模板：{hint} 为从 chunk 抽出的短提示（medium 用，hard 常省略）
THEME_QUERY_TEMPLATES: dict[str, list[str]] = {
    "protein": [
        "健身或减脂场景下，蛋白质摄入一般怎么安排？",
        "按体重计，蛋白质推荐大概在什么范围？",
        "优质蛋白可以从哪些食物获取？",
        "关于{hint}，指南或资料里怎么说？",
    ],
    "who_pa": [
        "成年人每周中等强度身体活动建议量是多少？",
        "身体活动指南对久坐有什么提醒？",
        "每周增强肌肉力量的活动怎么安排？",
        "关于{hint}，活动量建议如何理解？",
    ],
    "cn_diet": [
        "中国居民膳食指南有哪些核心要点？",
        "为什么强调食物多样？",
        "膳食里对盐油糖酒通常怎么建议？",
        "关于{hint}，膳食准则怎么说？",
    ],
    "fat_loss_myth": [
        "减脂期常见饮食误区有哪些？",
        "不吃主食一定能更快减脂吗？",
        "减脂期有氧是不是越多越好？",
        "关于{hint}，减脂建议怎么看？",
    ],
    "hydration": [
        "高强度训练时补水要注意什么？",
        "出汗多时要不要补电解质？",
        "运动饮料什么时候更合适？",
        "关于{hint}，饮水建议是什么？",
    ],
    "strength": [
        "力量训练新手每周练几次比较合适？",
        "什么是渐进超负荷？",
        "新手全身训练应覆盖哪些动作模式？",
        "关于{hint}，力量训练怎么安排？",
    ],
    "safety": [
        "FitPilot 会不会做疾病诊断或开药？",
        "训练时胸痛应该怎么办？",
        "出现锐痛或眩晕还能否继续加重量？",
        "关于{hint}，安全边界是什么？",
    ],
    "salt": [
        "膳食里盐/钠摄入一般怎么控制？",
        "减盐有哪些可执行建议？",
        "关于{hint}，盐摄入上限怎么理解？",
    ],
    "healthy_diet": [
        "平衡膳食通常强调哪些食物类别？",
        "蔬果和全谷在日常饮食中怎么安排？",
        "关于{hint}，健康饮食要点是什么？",
    ],
    "obesity": [
        "超重或肥胖管理有哪些基础建议？",
        "体重管理通常从哪些方面入手？",
        "关于{hint}，资料怎么建议？",
    ],
    "usda_food": [
        "{hint}每100克大概多少热量和蛋白质？",
        "USDA 食物宏量数据可以用来估算热量吗？",
        "如何从食物宏量条目里读 kcal 和蛋白？",
    ],
    "fitness_guide": [
        "全民健身或科学健身指南强调什么？",
        "关于{hint}，健身指导怎么说？",
    ],
    "children_pa": [
        "儿童青少年每天应活动多久？",
        "青少年娱乐性屏幕时间有什么建议？",
        "关于{hint}，儿童活动建议是什么？",
    ],
    "older_pa": [
        "老年人身体活动有什么额外建议？",
        "老年人如何结合平衡与防跌倒训练？",
        "关于{hint}，老年活动指南怎么说？",
    ],
    "weight_mgmt": [
        "减重或体重管理常见原则有哪些？",
        "热量与体重管理如何理解？",
        "关于{hint}，减重建议是什么？",
    ],
    "added_sugar": [
        "添加糖和含糖饮料有什么建议？",
        "如何理解控糖相关建议？",
        "关于{hint}，糖摄入怎么看？",
    ],
}

Q_PREFIX = ["", "请问", "想了解一下", "帮我看看"]
Q_SUFFIX = ["？", "呢？", "有什么建议？"]

HARD_SWAPS: list[tuple[str, list[str]]] = [
    ("蛋白质", ["优质蛋白摄入", "蛋白宏量", "增肌相关宏量"]),
    ("蛋白", ["优质蛋白", "宏量蛋白"]),
    ("减脂期", ["体脂管理阶段", "控制体脂阶段"]),
    ("减脂", ["控制体脂", "体脂管理"]),
    ("主食", ["谷薯类", "碳水主粮"]),
    ("身体活动", ["体力活动", "运动活动量"]),
    ("中等强度", ["中等费力程度", "呼吸加快但仍能说话的强度"]),
    ("力量训练", ["抗阻训练", "肌力训练"]),
    ("饮水", ["补水", "液体摄入"]),
    ("电解质", ["钠钾等矿物质", "盐分与矿物质"]),
    ("膳食指南", ["居民饮食指导", "平衡膳食建议"]),
    ("久坐", ["长时间静坐", "静坐少动"]),
    ("诊断", ["下医学结论", "临床确诊"]),
    ("开药", ["开具处方药", "用药处方"]),
    ("热量", ["能量", "卡路里"]),
    ("每周", ["七天内", "按周计"]),
    ("儿童", ["未成年人", "学龄儿童"]),
    ("老年", ["高龄人群", "年长者"]),
]

# 允许进入 expect_any 的指南数字（避免 FDC/页码/年份噪声）
NUMBER_ALLOWLIST = {"1.6", "2.2", "150", "300", "75", "60", "5", "5g", "100"}

ZH_STOPWORDS = {
    "根据",
    "可以",
    "建议",
    "以及",
    "或者",
    "我们",
    "进行",
    "通过",
    "相关",
    "内容",
    "一般",
    "通常",
    "如果",
    "因为",
    "所以",
    "这个",
    "那个",
    "什么",
    "怎么",
    "如何",
    "是否",
    "需要",
    "包括",
    "其中",
    "还有",
    "一些",
    "一种",
    "方面",
    "问题",
    "情况",
    "资料",
    "指南",
    "文档",
}

# 主题 ↔ 文档强冲突：document_id/title 命中则拒绝（弱匹配灌水）
THEME_DOC_EXCLUDE: dict[str, list[str]] = {
    "who_pa": ["食品基础", "foundation_foods", "fdc", "宏量条目", "foundation_food"],
    "hydration": ["foundation_foods", "食品基础", "fdc"],
    "obesity": ["foundation_foods", "食品基础", "salt_reduction", "减盐"],
    "salt": ["foundation_foods", "食品基础", "fdc"],
    "protein": ["foundation_foods_macros"],
    "cn_diet": ["foundation_foods", "fdc"],
    "healthy_diet": ["foundation_foods_macros", "fdc"],
    "strength": ["foundation_foods", "食品基础", "fdc"],
    "fat_loss_myth": ["foundation_foods", "fdc"],
    "fitness_guide": ["foundation_foods", "fdc"],
    "children_pa": ["foundation_foods", "食品基础", "fdc"],
    "older_pa": ["foundation_foods", "食品基础", "fdc"],
    "weight_mgmt": ["foundation_foods_macros", "fdc"],
    "added_sugar": ["foundation_foods_macros", "fdc"],
    "safety": ["foundation_foods", "fdc"],
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _norm(s: str) -> str:
    return (s or "").lower()


def _in_text(term: str, text: str) -> bool:
    if not term:
        return False
    return _norm(term) in _norm(text)


def load_chunks(bm25_path: Path = BM25) -> list[dict[str, Any]]:
    data = _load_json(bm25_path)
    payloads = data.get("payloads") or {}
    out: list[dict[str, Any]] = []
    for cid, raw in payloads.items():
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        if len(text) < 60:
            continue
        # 跳过明显目录/来源声明块
        if text.count("http") > 3 and len(text) < 200:
            continue
        out.append(
            {
                "chunk_id": str(raw.get("chunk_id") or cid),
                "document_id": str(raw.get("document_id") or ""),
                "title": str(raw.get("title") or ""),
                "text": text,
                "source_path": str(raw.get("source_path") or ""),
            }
        )
    return out


def score_theme(text: str, keys: list[str]) -> int:
    return sum(1 for k in keys if _in_text(k, text))


def assign_themes(text: str, *, min_score: int = 1) -> list[tuple[str, int]]:
    """返回 [(theme, score), ...]，按 score 降序；允许一块多主题候选。"""
    scored: list[tuple[str, int]] = []
    for theme, keys in THEME_KEYS.items():
        sc = score_theme(text, keys)
        if sc >= min_score:
            scored.append((theme, sc))
    scored.sort(key=lambda x: (-x[1], x[0]))
    return scored


def assign_theme(text: str) -> str | None:
    scored = assign_themes(text, min_score=2)
    if not scored:
        return None
    return scored[0][0]


def theme_doc_compatible(
    theme: str,
    *,
    document_id: str,
    title: str,
    text: str,
    score: int,
) -> bool:
    """主题-文档门控：弱匹配或强冲突文档一律拒绝。"""
    if score < 2:
        return False
    blob = f"{document_id} {title}".lower()
    for pat in THEME_DOC_EXCLUDE.get(theme, []):
        if pat.lower() in blob:
            return False
    if theme == "usda_food":
        if not (
            extract_food_name(text)
            or _in_text("kcal", text)
            or _in_text("蛋白", text)
            or _in_text("USDA", text)
        ):
            return False
    return True


def extract_numbers(text: str) -> list[str]:
    nums = re.findall(r"\d+(?:\.\d+)?(?:g)?", text, flags=re.IGNORECASE)
    uniq: list[str] = []
    for n in nums:
        if n in uniq:
            continue
        if len(n) > 6:
            continue
        uniq.append(n)
        if len(uniq) >= 12:
            break
    return uniq


def _number_allowed(n: str, text: str) -> bool:
    """仅 allowlist 或带单位邻接的数字；拒绝 FDC/年份/裸短数字。"""
    raw = n.lower().rstrip("g")
    if n.lower() in NUMBER_ALLOWLIST or raw in NUMBER_ALLOWLIST:
        return _in_text(raw if raw in text.lower() else n, text) or _in_text(n, text)
    if re.fullmatch(r"\d{5,}", raw):
        return False
    if re.fullmatch(r"(?:19|20)\d{2}", raw):
        return False
    if re.fullmatch(r"\d", raw):
        return False
    # 单位邻接：g/kg、克、分钟、小时、次/周 等
    if re.search(
        rf"(?<!\d){re.escape(raw)}\s*(?:g/kg|克/千克|克|分钟|小时|天|次|%|kcal)",
        text,
        flags=re.IGNORECASE,
    ):
        return True
    if re.search(
        rf"(?:每周|每天|每日|至少|约|≥|<=|不少于|不超过)\s*{re.escape(raw)}(?!\d)",
        text,
    ):
        return True
    return False


def extract_food_name(text: str) -> str | None:
    # USDA 宏量条目常见：**中文名**（English...）
    m = re.search(r"\*\*([^*]{2,40})\*\*", text)
    if m:
        name = m.group(1).strip()
        # 去掉过长说明
        name = re.split(r"[（(，,]", name, maxsplit=1)[0].strip()
        if 2 <= len(name) <= 24:
            return name
    return None


def _is_ascii_slug(term: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_\-]{1,}", term))


def _term_ok_for_expect(term: str, text: str) -> bool:
    if not term or not _in_text(term, text):
        return False
    if term in ZH_STOPWORDS:
        return False
    if re.fullmatch(r"\d+(?:\.\d+)?g?", term, flags=re.IGNORECASE):
        return _number_allowed(term, text)
    if _is_ascii_slug(term):
        # 仅当正文出现该词（非 document_id 泄漏）
        return _in_text(term, text) and len(term) >= 3
    # 中文：至少 2 字；单字过泛
    if re.fullmatch(r"[\u4e00-\u9fff]+", term):
        return len(term) >= 2
    return len(term) >= 2


def pick_expect_any(
    *,
    theme: str,
    text: str,
    document_id: str,
    rng: random.Random,
) -> list[str]:
    """从源 chunk 抽 2–3 个共现确认词；禁止 FDC/年份/slug 灌袋。"""
    del document_id  # 不再把 document_id 片段塞进 expect
    keys = [k for k in THEME_KEYS.get(theme, []) if _term_ok_for_expect(k, text)]
    # 主题键优先长词
    keys.sort(key=len, reverse=True)
    nums = [n for n in extract_numbers(text) if _number_allowed(n, text)]

    candidates: list[str] = []
    for k in keys:
        if k not in candidates:
            candidates.append(k)
    for n in nums:
        # 归一：5g 保留，纯数字用原文形式
        token = n if n.lower() in NUMBER_ALLOWLIST else re.sub(r"g$", "", n, flags=re.I)
        if _term_ok_for_expect(token, text) and token not in candidates:
            candidates.append(token)
        if len(candidates) >= 4:
            break

    if theme == "usda_food":
        food = extract_food_name(text)
        if food and food not in candidates:
            candidates.insert(0, food)

    if len([c for c in candidates if _in_text(c, text)]) < 2:
        zh = re.findall(r"[\u4e00-\u9fff]{2,6}", text)
        for w in zh:
            if w in ZH_STOPWORDS:
                continue
            if not _term_ok_for_expect(w, text):
                continue
            if w not in candidates:
                candidates.append(w)
            if len([c for c in candidates if _in_text(c, text)]) >= 3:
                break

    out: list[str] = []
    for e in candidates:
        if e and e not in out and _in_text(e, text):
            # 丢掉被更长词覆盖的短词（降低袋内冗余）
            if any(e != o and e in o for o in out):
                continue
            out = [o for o in out if not (o != e and o in e)]
            out.append(e)
        if len(out) >= 3:
            break

    if len(out) < 2:
        return []
    if rng.random() < 0.25 and len(out) == 3:
        head, tail = out[:2], out[2:]
        rng.shuffle(tail)
        out = head + tail
    return out


def harden_query(q: str, rng: random.Random) -> str:
    core = q.rstrip("？?。.!！")
    for src, alts in HARD_SWAPS:
        if src in core and rng.random() < 0.85:
            core = core.replace(src, rng.choice(alts), 1)
    # 弱化数字字面（expect 仍用原文数字判分）
    if rng.random() < 0.55:
        core = (
            core.replace("150", "两小时半左右")
            .replace("300", "约五小时")
            .replace("1.6", "约一点六")
            .replace("2.2", "约二点二")
            .replace("60", "约一小时")
            .replace("75", "约七十五")
        )
    pre = rng.choice(Q_PREFIX) if rng.random() < 0.35 else ""
    suf = rng.choice(Q_SUFFIX) if rng.random() < 0.5 else "？"
    out = f"{pre}{core}{suf}".strip()
    if not out.endswith(("？", "?", "。")):
        out += "？"
    return out


def _primary_keep_terms(expect_any: list[str]) -> list[str]:
    """hard 改写时保留主内容词，避免问句被掏空。"""
    keep: list[str] = []
    for e in expect_any:
        if not e:
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?g?", e, flags=re.IGNORECASE):
            continue
        if re.search(r"[\u4e00-\u9fff]", e) and len(e) >= 2:
            keep.append(e)
            if len(keep) >= 1:
                break
    return keep


def strip_expect_from_query(
    query: str,
    expect_any: list[str],
    *,
    keep_terms: list[str] | None = None,
) -> str:
    """最多替换 1 个整词/短语泄漏；禁止半截替换（如 蛋白⊂蛋白质）。"""
    keep = {k for k in (keep_terms or []) if k}
    q = query
    candidates: list[tuple[str, int, int]] = []
    for e in sorted((x for x in expect_any if x), key=len, reverse=True):
        if e in keep:
            continue
        if e.isdigit() or re.fullmatch(r"\d+(?:\.\d+)?g?", e, flags=re.IGNORECASE):
            continue
        if len(e) < 2:
            continue
        for m in re.finditer(re.escape(e), q):
            start, end = m.span()
            left = q[start - 1] if start > 0 else ""
            right = q[end] if end < len(q) else ""
            # ascii：禁止嵌在字母数字中间
            if re.match(r"[A-Za-z0-9]", left) or re.match(r"[A-Za-z0-9]", right):
                continue
            if re.search(r"[\u4e00-\u9fff]", e):
                # 左侧贴着汉字 → 嵌在更长词中（优质|蛋白|质）
                if left and re.match(r"[\u4e00-\u9fff]", left):
                    continue
                # 短词右侧贴汉字 → 多半是「蛋白质」类半截；长短语允许「力量训练有…」
                if right and re.match(r"[\u4e00-\u9fff]", right) and len(e) < 4:
                    continue
            candidates.append((e, start, end))
            break
        if candidates:
            break  # 最长优先，只取一个

    if candidates:
        _, start, end = candidates[0]
        q = q[:start] + "该主题" + q[end:]

    q = re.sub(r"该主题（与该主题相关）", "该主题", q)
    q = re.sub(r"（与该主题相关）", "", q)
    q = re.sub(r"该主题+", "该主题", q)
    return q


def query_is_acceptable(query: str) -> bool:
    """拒绝残缺 hard 问句（半截占位、过短、重复占位）。"""
    q = (query or "").strip()
    if len(re.sub(r"[？?。.\s]", "", q)) < 8:
        return False
    if "相关内容相关内容" in q or "该主题该主题" in q:
        return False
    if q.count("相关内容") > 1 or q.count("该主题") > 2:
        return False
    # 半截：汉字+占位+汉字（如 优质相关内容质）
    if re.search(r"[\u4e00-\u9fff](?:相关内容|该主题)[\u4e00-\u9fff]", q):
        return False
    return True


def build_query(
    *,
    theme: str,
    text: str,
    expect_any: list[str],
    difficulty: str,
    rng: random.Random,
) -> str:
    templates = THEME_QUERY_TEMPLATES.get(theme) or ["关于{hint}，资料怎么说？"]
    hint = ""
    food = extract_food_name(text) if theme == "usda_food" else None
    if food:
        hint = food
    else:
        for e in expect_any:
            if re.search(r"[\u4e00-\u9fff]", e) and 2 <= len(e) <= 8:
                hint = e
                break
        if not hint:
            hint = expect_any[0] if expect_any else theme

    # hard/medium 优先无 hint 模板，降低泄漏
    if difficulty == "hard":
        generics = [t for t in templates if "{hint}" not in t]
        tmpl = rng.choice(generics) if generics else rng.choice(templates)
    elif difficulty == "medium":
        generics = [t for t in templates if "{hint}" not in t]
        pool = generics + templates
        tmpl = rng.choice(pool)
    else:
        tmpl = rng.choice(templates)

    if "{hint}" in tmpl:
        if difficulty == "hard":
            tmpl = tmpl.replace("{hint}", "该主题")
        else:
            tmpl = tmpl.replace("{hint}", hint)

    if difficulty == "easy":
        leak = next((e for e in expect_any if re.search(r"[\u4e00-\u9fff]", e)), "")
        if leak and leak not in tmpl and rng.random() < 0.45:
            tmpl = f"{tmpl.rstrip('？?')}（与{leak}相关）？"
        out = tmpl if tmpl.endswith(("？", "?")) else tmpl + "？"
        return out if query_is_acceptable(out) else ""

    keep = _primary_keep_terms(expect_any) if difficulty == "hard" else []

    if difficulty == "medium":
        pre = rng.choice(Q_PREFIX) if rng.random() < 0.35 else ""
        out = f"{pre}{tmpl}".strip()
        if not out.endswith(("？", "?")):
            out += "？"
        # medium：仅当泄漏偏高时剥一次，且不掏空主词
        if leak_ratio(out, expect_any) > 0.35:
            out = strip_expect_from_query(out, expect_any, keep_terms=keep)
        return out if query_is_acceptable(out) else ""

    # hard：主要靠 HARD_SWAPS + 数字口语化；泄漏高时尝试剥一次，失败则保留未剥版本
    out = harden_query(tmpl, rng)
    if leak_ratio(out, expect_any) > 0.30:
        stripped = strip_expect_from_query(out, expect_any, keep_terms=keep)
        if query_is_acceptable(stripped) and leak_ratio(stripped, expect_any) <= 0.35:
            out = stripped
    return out if query_is_acceptable(out) else ""


def leak_ratio(query: str, expect_any: list[str]) -> float:
    if not expect_any:
        return 0.0
    hit = sum(1 for e in expect_any if e and e in query)
    return hit / len(expect_any)


def build_relevance(expect_any: list[str]) -> list[dict[str, Any]]:
    rel: list[dict[str, Any]] = []
    for i, e in enumerate(expect_any[:4]):
        # 数字/专名 grade 2，其余 1
        grade = 2 if (re.fullmatch(r"\d+(?:\.\d+)?", e) or i == 0) else 1
        rel.append({"match": e, "grade": grade})
    return rel


def generate_suite(
    *,
    target: int = 300,
    seed: int = SEED,
    include_fewshot: bool = True,
    max_per_theme: int = 40,
    max_per_doc: int = 28,
    max_paraphrase_per_anchor: int = 1,
    max_variants_per_chunk: int = 3,
    bm25_path: Path = BM25,
) -> dict[str, Any]:
    rng = random.Random(seed)
    chunks = load_chunks(bm25_path)
    by_theme: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ch in chunks:
        for theme, sc in assign_themes(ch["text"], min_score=2):
            if not theme_doc_compatible(
                theme,
                document_id=ch["document_id"],
                title=ch.get("title") or "",
                text=ch["text"],
                score=sc,
            ):
                continue
            by_theme[theme].append(ch)

    cases: list[dict[str, Any]] = []
    seen_queries: set[str] = set()
    doc_counts: dict[str, int] = defaultdict(int)
    theme_counts: dict[str, int] = defaultdict(int)
    chunk_variant_counts: dict[str, int] = defaultdict(int)

    # 1) fewshot 锚点
    if include_fewshot and FEWSHOT.exists():
        seed_data = _load_json(FEWSHOT)
        for c in seed_data.get("cases") or []:
            q = str(c.get("query") or "").strip()
            if not q or q in seen_queries:
                continue
            nc = {
                "id": str(c.get("id") or f"seed_{len(cases)}"),
                "query": q,
                "expect_any": list(c.get("expect_any") or []),
                "difficulty": "easy",
                "theme": "fewshot_seed",
                "origin": "fewshot",
            }
            if c.get("relevance"):
                nc["relevance"] = c["relevance"]
            if c.get("source_document_id"):
                nc["source_document_id"] = c["source_document_id"]
            if c.get("source_chunk_id"):
                nc["source_chunk_id"] = c["source_chunk_id"]
            cases.append(nc)
            seen_queries.add(q)
            for j in range(max_paraphrase_per_anchor):
                hq = harden_query(q, rng)
                keep = _primary_keep_terms(nc["expect_any"])
                if leak_ratio(hq, nc["expect_any"]) > 0.30:
                    hq = strip_expect_from_query(hq, nc["expect_any"], keep_terms=keep)
                if not query_is_acceptable(hq):
                    continue
                if hq in seen_queries or leak_ratio(hq, nc["expect_any"]) > 0.35:
                    continue
                cases.append(
                    {
                        "id": f"{nc['id']}_hard{j+1}",
                        "query": hq,
                        "expect_any": list(nc["expect_any"]),
                        "difficulty": "hard",
                        "theme": "fewshot_seed",
                        "origin": "fewshot_paraphrase",
                        **(
                            {"source_document_id": nc["source_document_id"]}
                            if nc.get("source_document_id")
                            else {}
                        ),
                        **(
                            {"source_chunk_id": nc["source_chunk_id"]}
                            if nc.get("source_chunk_id")
                            else {}
                        ),
                    }
                )
                seen_queries.add(hq)

    kb_budget = max(0, target - len(cases))
    want_easy = int(kb_budget * 0.15)
    want_med = int(kb_budget * 0.40)
    want_hard = kb_budget - want_easy - want_med
    diff_quota = {"easy": want_easy, "medium": want_med, "hard": want_hard}

    themes = sorted(by_theme.keys())
    rng.shuffle(themes)

    themed_pools: dict[str, list[dict[str, Any]]] = {}
    for th in themes:
        pool = list(by_theme[th])
        rng.shuffle(pool)
        by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for ch in pool:
            by_doc[ch["document_id"] or "_"].append(ch)
        interleaved: list[dict[str, Any]] = []
        doc_lists = list(by_doc.values())
        rng.shuffle(doc_lists)
        idx = 0
        while any(doc_lists):
            dl = doc_lists[idx % len(doc_lists)]
            if dl:
                interleaved.append(dl.pop(0))
            else:
                doc_lists.pop(idx % len(doc_lists))
                if not doc_lists:
                    break
                continue
            idx += 1
        themed_pools[th] = interleaved

    pointers = {th: 0 for th in themes}
    stalled = 0
    while len(cases) < target and stalled < 20000:
        progressed = False
        for th in themes:
            if len(cases) >= target:
                break
            if theme_counts[th] >= max_per_theme:
                continue
            pool = themed_pools.get(th) or []
            i = pointers[th]
            if i >= len(pool):
                continue
            ch = pool[i]
            pointers[th] = i + 1
            doc_id = ch["document_id"] or "_"
            if doc_counts[doc_id] >= max_per_doc:
                continue
            if chunk_variant_counts[ch["chunk_id"]] >= max_variants_per_chunk:
                continue

            # 再次校验主题分（池内已门控，这里兜底）
            theme_scores = {t: s for t, s in assign_themes(ch["text"], min_score=2)}
            if th not in theme_scores or not theme_doc_compatible(
                th,
                document_id=doc_id,
                title=ch.get("title") or "",
                text=ch["text"],
                score=theme_scores[th],
            ):
                continue

            expect = pick_expect_any(
                theme=th, text=ch["text"], document_id=doc_id, rng=rng
            )
            if not expect or len(expect) > 3:
                expect = expect[:3] if expect else []
            if len(expect) < 2:
                continue

            remaining = [d for d, n in diff_quota.items() if n > 0]
            if not remaining:
                difficulty = rng.choice(["medium", "hard"])
            else:
                weights = [diff_quota[d] for d in remaining]
                difficulty = rng.choices(remaining, weights=weights, k=1)[0]

            query = ""
            max_leak = 0.55 if difficulty == "easy" else 0.30
            for _attempt in range(8):
                cand = build_query(
                    theme=th,
                    text=ch["text"],
                    expect_any=expect,
                    difficulty=difficulty,
                    rng=rng,
                )
                if not cand or not query_is_acceptable(cand):
                    continue
                if leak_ratio(cand, expect) > max_leak:
                    keep = _primary_keep_terms(expect) if difficulty == "hard" else []
                    cand = strip_expect_from_query(
                        harden_query(cand, rng), expect, keep_terms=keep
                    )
                    if (
                        not query_is_acceptable(cand)
                        or leak_ratio(cand, expect) > max_leak
                    ):
                        continue
                if cand in seen_queries:
                    # 轻量去歧义，避免同模板把整主题抽干
                    food = extract_food_name(ch["text"])
                    tip = food or (ch.get("title") or doc_id)[:16]
                    if tip:
                        alt = f"{cand.rstrip('？?。')}（{tip}）？"
                        if alt not in seen_queries and query_is_acceptable(alt):
                            cand = alt
                        else:
                            continue
                    else:
                        continue
                query = cand
                break
            if not query:
                continue
            if sum(1 for e in expect if _in_text(e, ch["text"])) < 2:
                continue

            cid = f"kb_{th}_{doc_id[:24]}_{len(cases):04d}"
            case: dict[str, Any] = {
                "id": re.sub(r"[^a-zA-Z0-9_\u4e00-\u9fff\-]", "_", cid)[:80],
                "query": query,
                "expect_any": expect,
                "difficulty": difficulty,
                "theme": th,
                "origin": "kb",
                "source_document_id": doc_id,
                "source_chunk_id": ch["chunk_id"],
                "relevance": build_relevance(expect),
            }
            cases.append(case)
            seen_queries.add(query)
            doc_counts[doc_id] += 1
            theme_counts[th] += 1
            chunk_variant_counts[ch["chunk_id"]] += 1
            if difficulty in diff_quota and diff_quota[difficulty] > 0:
                diff_quota[difficulty] -= 1
            progressed = True
            if len(cases) >= target:
                break
        if not progressed:
            stalled += 1
        else:
            stalled = 0

    cases = cases[:target]
    theme_hist: dict[str, int] = defaultdict(int)
    diff_hist: dict[str, int] = defaultdict(int)
    origin_hist: dict[str, int] = defaultdict(int)
    for c in cases:
        theme_hist[str(c.get("theme"))] += 1
        diff_hist[str(c.get("difficulty"))] += 1
        origin_hist[str(c.get("origin"))] += 1

    return {
        "name": "fitpilot-golden-rag-kb-v4",
        "description": (
            "大评测总集 v4：KB chunk 主题分层出题；expect_any 收紧为源 chunk 2–3 核心词；"
            "hard 改写禁止半截占位；主题-文档门控；用于抬高 Precision/TermRecall 可解释性。"
        ),
        "min_hit_rate": 0.7,
        "generator": {
            "script": "scripts/generate_rag_suite_from_kb.py",
            "seed": seed,
            "target": target,
            "max_per_theme": max_per_theme,
            "max_per_doc": max_per_doc,
            "bm25_chunks_loaded": len(chunks),
            "theme_counts": dict(sorted(theme_hist.items(), key=lambda x: -x[1])),
            "difficulty_counts": dict(diff_hist),
            "origin_counts": dict(origin_hist),
            "unique_themes": len([t for t in theme_hist if t != "fewshot_seed"]),
            "unique_source_docs": len(
                {c.get("source_document_id") for c in cases if c.get("source_document_id")}
            ),
            "unique_expect_any": len({tuple(c.get("expect_any") or []) for c in cases}),
        },
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="从 KB 生成 golden_rag 评测集")
    parser.add_argument("--target", type=int, default=300)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--bm25", type=Path, default=BM25)
    parser.add_argument("--max-per-theme", type=int, default=40)
    parser.add_argument("--max-per-doc", type=int, default=28)
    parser.add_argument("--no-fewshot", action="store_true")
    args = parser.parse_args()

    if not args.bm25.exists():
        raise SystemExit(f"BM25 不存在: {args.bm25}（请先 ingest）")

    suite = generate_suite(
        target=max(50, min(500, args.target)),
        seed=args.seed,
        include_fewshot=not args.no_fewshot,
        max_per_theme=args.max_per_theme,
        max_per_doc=args.max_per_doc,
        bm25_path=args.bm25,
    )
    _dump_json(args.out, suite)
    gen = suite.get("generator") or {}
    print(f"wrote {args.out} cases={len(suite['cases'])}")
    print(f"  themes={gen.get('theme_counts')}")
    print(f"  difficulty={gen.get('difficulty_counts')}")
    print(f"  origin={gen.get('origin_counts')}")
    print(f"  unique_source_docs={gen.get('unique_source_docs')}")


if __name__ == "__main__":
    main()
