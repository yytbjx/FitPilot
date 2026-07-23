"""查询理解：规则改写 + 可选小模型改写 + Multi-Query 扩展 + 结构化分析。"""

from __future__ import annotations

import re
from typing import Any, Literal

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

QueryType = Literal[
    "factoid",
    "how_to",
    "why",
    "comparison",
    "personal",
    "plan",
    "risk",
    "other",
]

_FITNESS_SYNONYMS: dict[str, list[str]] = {
    "减脂": ["脂肪减少", "减重", "热量赤字"],
    "增肌": ["肌肉增长", "力量训练", "hypertrophy"],
    "蛋白": ["蛋白质", "氨基酸"],
    "深蹲": ["squat", "下肢训练"],
    "硬拉": ["deadlift", "后链"],
    "热量": ["卡路里", "kcal", "能量摄入"],
}

_ENTITY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("protein", re.compile(r"蛋白(?:质)?")),
    ("calorie", re.compile(r"热量|卡路里|kcal")),
    ("fat_loss", re.compile(r"减脂|减重|脂肪")),
    ("muscle", re.compile(r"增肌|肌肉")),
    ("squat", re.compile(r"深蹲")),
    ("deadlift", re.compile(r"硬拉")),
    ("hydration", re.compile(r"补水|饮水|脱水")),
    ("recovery", re.compile(r"恢复|睡眠|疲劳")),
]


def _is_complex(query: str) -> bool:
    q = query or ""
    if len(q) > 40:
        return True
    if re.search(r"(并且|同时|以及|对比|区别|为什么|怎么|如何)", q):
        return True
    return q.count("？") + q.count("?") > 1


def classify_query_type(query: str) -> QueryType:
    q = query or ""
    if re.search(r"(胸痛|骨折|处方|诊断|心脏病|晕厥|吃药)", q):
        return "risk"
    if re.search(r"(我的|根据我|档案|最近.*记录|体重)", q):
        return "personal"
    if re.search(r"(计划|安排训练|调整饮食|生成计划)", q):
        return "plan"
    if re.search(r"(对比|区别|哪个更好|差异)", q):
        return "comparison"
    if re.search(r"(为什么|原因|机制|原理)", q):
        return "why"
    if re.search(r"(怎么|如何|方法|步骤|要领)", q):
        return "how_to"
    if len(q) <= 20:
        return "factoid"
    return "other"


def extract_entities(query: str) -> list[str]:
    q = query or ""
    found: list[str] = []
    for name, pat in _ENTITY_PATTERNS:
        if pat.search(q):
            found.append(name)
    return found


def extract_time_range(query: str) -> dict[str, Any] | None:
    q = query or ""
    m = re.search(r"最近\s*(\d+)\s*(天|周|月)", q)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        days = n * (7 if unit == "周" else 30 if unit == "月" else 1)
        return {"raw": m.group(0), "days": days}
    if "两周" in q:
        return {"raw": "两周", "days": 14}
    if "一周" in q or "本周" in q:
        return {"raw": "一周", "days": 7}
    return None


def rewrite_query(query: str, *, history: list[str] | None = None) -> str:
    """轻量规则改写：补全健身语境。"""
    q = (query or "").strip()
    if not q:
        return q
    if history:
        last = history[-1][:80]
        if len(q) < 12 and not re.search(r"(训练|饮食|蛋白|热量)", q):
            return f"{last}；追问：{q}"
    if not re.search(r"(健身|训练|饮食|营养|运动)", q):
        return f"健身与营养：{q}"
    return q


async def rewrite_query_llm(query: str, *, history: list[str] | None = None) -> str:
    """可选：用 0.5B 级小模型改写检索查询（失败则回退规则）。"""
    base = rewrite_query(query, history=history)
    settings = get_settings()
    if not settings.ollama_use_llm_rewrite:
        return base
    try:
        from app.services.ollama_client import get_ollama_client

        hist = ""
        if history:
            hist = f"\n上文：{history[-1][:120]}"
        prompt = (
            "将用户问题改写成适合健身/营养知识检索的短查询。"
            "只输出改写后的查询，不要解释。\n"
            f"原问题：{query}{hist}"
        )
        resp = await get_ollama_client().chat(
            [
                {"role": "system", "content": "你是检索查询改写器，输出一句话。"},
                {"role": "user", "content": prompt},
            ],
            role="rewrite",
            options={"num_predict": 48, "temperature": 0.1},
        )
        text = ((resp.get("message") or {}).get("content") or "").strip()
        text = text.splitlines()[0].strip().strip('"').strip("「」")
        if 2 <= len(text) <= 120:
            return text
    except Exception as exc:  # noqa: BLE001
        logger.warning("llm_rewrite_failed", error=str(exc))
    return base


def expand_queries(query: str, *, max_variants: int = 3) -> list[str]:
    """生成 Multi-Query 变体。"""
    base = rewrite_query(query)
    variants: list[str] = [base]
    for term, alts in _FITNESS_SYNONYMS.items():
        if term in base:
            for alt in alts[:1]:
                variants.append(base.replace(term, alt, 1))
    if base.endswith("？"):
        variants.append(base.rstrip("？") + "的方法")
    elif base.endswith("?"):
        variants.append(base.rstrip("?") + " methods")

    seen: set[str] = set()
    out: list[str] = []
    for v in variants:
        v = v.strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
        if len(out) >= max_variants:
            break
    return out


def analyze_query(query: str, *, history: list[str] | None = None) -> dict[str, Any]:
    """同步规则版（默认路径，零 LLM 开销）。"""
    rewritten = rewrite_query(query, history=history)
    variants = expand_queries(rewritten)
    qtype = classify_query_type(query)
    entities = extract_entities(query)
    time_range = extract_time_range(query)
    return {
        "original": query,
        "rewritten": rewritten,
        "variants": variants,
        "use_multi_query": _is_complex(rewritten) or len(variants) > 1 or qtype in {"why", "comparison"},
        "llm_rewrite": False,
        "query_type": qtype,
        "entities": entities,
        "time_range": time_range,
        "requires_authority": qtype == "risk",
    }


async def analyze_query_async(query: str, *, history: list[str] | None = None) -> dict[str, Any]:
    """异步版：可选调用小模型改写后再 Multi-Query。"""
    rewritten = await rewrite_query_llm(query, history=history)
    variants = expand_queries(rewritten)
    if rewritten not in variants:
        variants = [rewritten] + [v for v in variants if v != rewritten]
        variants = variants[:3]
    base = analyze_query(query, history=history)
    base.update(
        {
            "rewritten": rewritten,
            "variants": variants,
            "use_multi_query": _is_complex(rewritten) or len(variants) > 1 or base["query_type"] in {"why", "comparison"},
            "llm_rewrite": get_settings().ollama_use_llm_rewrite,
        }
    )
    return base
