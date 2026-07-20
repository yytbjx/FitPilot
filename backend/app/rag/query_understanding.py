"""查询理解：规则改写 + 可选小模型改写 + Multi-Query 扩展。"""

from __future__ import annotations

import re
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_FITNESS_SYNONYMS: dict[str, list[str]] = {
    "减脂": ["脂肪减少", "减重", "热量赤字"],
    "增肌": ["肌肉增长", "力量训练", "hypertrophy"],
    "蛋白": ["蛋白质", "氨基酸"],
    "深蹲": ["squat", "下肢训练"],
    "硬拉": ["deadlift", "后链"],
    "热量": ["卡路里", "kcal", "能量摄入"],
}


def _is_complex(query: str) -> bool:
    q = query or ""
    if len(q) > 40:
        return True
    if re.search(r"(并且|同时|以及|对比|区别|为什么|怎么|如何)", q):
        return True
    return q.count("？") + q.count("?") > 1


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
    return {
        "original": query,
        "rewritten": rewritten,
        "variants": variants,
        "use_multi_query": _is_complex(rewritten) or len(variants) > 1,
        "llm_rewrite": False,
    }


async def analyze_query_async(query: str, *, history: list[str] | None = None) -> dict[str, Any]:
    """异步版：可选调用小模型改写后再 Multi-Query。"""
    rewritten = await rewrite_query_llm(query, history=history)
    variants = expand_queries(rewritten)
    # expand_queries 内部会再 rewrite_query，若 LLM 已改写则直接以 rewritten 为基
    if rewritten not in variants:
        variants = [rewritten] + [v for v in variants if v != rewritten]
        variants = variants[:3]
    return {
        "original": query,
        "rewritten": rewritten,
        "variants": variants,
        "use_multi_query": _is_complex(rewritten) or len(variants) > 1,
        "llm_rewrite": get_settings().ollama_use_llm_rewrite,
    }
