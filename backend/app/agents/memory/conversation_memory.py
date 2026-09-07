"""分层对话记忆：活跃轮次保留 + PG 原文归档 + 摘要向量召回 + 邻近扩展。"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from typing import Any, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.conversation_memory import ConversationMemory


def estimate_tokens(text: str) -> int:
    """粗估 token：中英混合按字符启发式（不依赖 tokenizer）。"""
    if not text:
        return 0
    # 中文偏 1 char≈1 token，英文偏 4 chars≈1 token；折中
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = max(0, len(text) - cjk)
    return max(1, cjk + (other + 3) // 4)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        fx = float(x)
        fy = float(y)
        dot += fx * fy
        na += fx * fx
        nb += fy * fy
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def summarize_turn(role: str, content: str, *, max_ratio: float = 1 / 3) -> str:
    """确定性摘要（不调 LLM）：截断到原文约 1/3，保留角色前缀。"""
    text = (content or "").strip()
    if not text:
        return f"{role}:"
    budget = max(24, int(len(text) * max_ratio))
    clipped = text if len(text) <= budget else text[: budget - 1] + "…"
    return f"{role}: {clipped}"


def importance_of(role: str, content: str) -> float:
    """简单重要性：用户长消息 / 含目标关键词更高。"""
    base = 0.55 if role == "user" else 0.45
    t = content or ""
    boost = 0.0
    for kw in ("目标", "计划", "忌口", "伤", "体重", "蛋白", "减脂", "增肌"):
        if kw in t:
            boost += 0.05
    if len(t) > 120:
        boost += 0.05
    return min(0.99, base + boost)


@dataclass
class MemoryFragment:
    message_id: str
    turn_index: int
    role: str
    content: str
    summary: str
    score: float = 0.0
    source: str = "core"  # core | recall | neighbor
    tokens: int = 0

    def __post_init__(self) -> None:
        if self.tokens <= 0:
            self.tokens = estimate_tokens(self.summary or self.content)


@dataclass
class ContextBundle:
    """分层记忆召回结果。"""

    core: list[MemoryFragment] = field(default_factory=list)
    recalled: list[MemoryFragment] = field(default_factory=list)
    neighbors: list[MemoryFragment] = field(default_factory=list)
    archival_count: int = 0

    def all_unique_by_turn(self) -> list[MemoryFragment]:
        by_turn: dict[int, MemoryFragment] = {}
        for frag in [*self.core, *self.recalled, *self.neighbors]:
            prev = by_turn.get(frag.turn_index)
            if prev is None or frag.score > prev.score:
                by_turn[frag.turn_index] = frag
        return [by_turn[k] for k in sorted(by_turn)]


async def _next_turn_index(db: AsyncSession, session_id: str) -> int:
    val = await db.scalar(
        select(func.coalesce(func.max(ConversationMemory.turn_index), -1)).where(
            ConversationMemory.session_id == session_id
        )
    )
    return int(val or -1) + 1


async def append_message(
    db: AsyncSession,
    *,
    user_id: int,
    session_id: str,
    role: str,
    content: str,
    task_id: str | None = None,
    message_id: str | None = None,
    embed: bool = True,
    extra: dict[str, Any] | None = None,
) -> ConversationMemory:
    """写入原始消息；可选生成摘要与向量（Recall 层）。"""
    settings = get_settings()
    mid = message_id or str(uuid.uuid4())
    turn = await _next_turn_index(db, session_id)
    summary = summarize_turn(role, content, max_ratio=settings.conversation_summary_ratio)
    importance = importance_of(role, content)
    vector: list[float] | None = None
    if embed and settings.conversation_memory_embed and content.strip():
        try:
            from app.rag.embeddings import embed_query

            vector = embed_query(summary)
        except Exception:  # noqa: BLE001 — 向量失败不阻断归档
            vector = None
    row = ConversationMemory(
        user_id=user_id,
        session_id=session_id,
        message_id=mid,
        turn_index=turn,
        role=role,
        content=content,
        summary=summary,
        embedding=vector,
        importance=importance,
        task_id=task_id,
        extra=extra or {},
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def load_recent_core(
    db: AsyncSession,
    *,
    session_id: str,
    k: int | None = None,
) -> list[MemoryFragment]:
    settings = get_settings()
    limit = k if k is not None else settings.conversation_core_k
    rows = (
        await db.scalars(
            select(ConversationMemory)
            .where(ConversationMemory.session_id == session_id)
            .order_by(ConversationMemory.turn_index.desc())
            .limit(max(1, limit))
        )
    ).all()
    rows = list(reversed(rows))
    return [
        MemoryFragment(
            message_id=r.message_id,
            turn_index=r.turn_index,
            role=r.role,
            content=r.content,
            summary=r.summary or summarize_turn(r.role, r.content),
            score=1.0,
            source="core",
        )
        for r in rows
    ]


async def recall_relevant(
    db: AsyncSession,
    *,
    session_id: str,
    query: str,
    top_n: int | None = None,
    exclude_turns: set[int] | None = None,
) -> list[MemoryFragment]:
    """按当前问题向量召回历史摘要（会话内）。"""
    settings = get_settings()
    n = top_n if top_n is not None else settings.conversation_recall_n
    exclude = exclude_turns or set()
    rows = (
        await db.scalars(
            select(ConversationMemory)
            .where(ConversationMemory.session_id == session_id)
            .order_by(ConversationMemory.turn_index.asc())
        )
    ).all()
    if not rows:
        return []

    qvec: list[float] | None = None
    if settings.conversation_memory_embed and query.strip():
        try:
            from app.rag.embeddings import embed_query

            qvec = embed_query(query)
        except Exception:  # noqa: BLE001
            qvec = None

    scored: list[MemoryFragment] = []
    q_lower = (query or "").lower()
    for r in rows:
        if r.turn_index in exclude:
            continue
        if float(r.importance or 0) < settings.conversation_min_importance and not qvec:
            continue
        if qvec and isinstance(r.embedding, list) and r.embedding:
            score = _cosine(qvec, r.embedding)
        else:
            # 无向量时用关键词重叠兜底
            blob = f"{r.summary or ''} {r.content or ''}".lower()
            hits = sum(1 for tok in q_lower.replace("，", " ").split() if tok and tok in blob)
            score = min(1.0, hits * 0.2 + float(r.importance or 0.3) * 0.5)
        if score < 0.15:
            continue
        scored.append(
            MemoryFragment(
                message_id=r.message_id,
                turn_index=r.turn_index,
                role=r.role,
                content=r.content,
                summary=r.summary or summarize_turn(r.role, r.content),
                score=float(score),
                source="recall",
            )
        )
    scored.sort(key=lambda x: x.score, reverse=True)
    return scored[: max(1, n)]


async def expand_neighbors(
    db: AsyncSession,
    *,
    session_id: str,
    anchors: Sequence[MemoryFragment],
    radius: int | None = None,
) -> list[MemoryFragment]:
    """为召回锚点同步索引前后 R 轮，保证语义连贯。"""
    settings = get_settings()
    r = radius if radius is not None else settings.conversation_neighbor_radius
    if not anchors or r <= 0:
        return []
    needed: set[int] = set()
    for a in anchors:
        for t in range(a.turn_index - r, a.turn_index + r + 1):
            if t >= 0:
                needed.add(t)
    for a in anchors:
        needed.discard(a.turn_index)
    if not needed:
        return []
    rows = (
        await db.scalars(
            select(ConversationMemory).where(
                ConversationMemory.session_id == session_id,
                ConversationMemory.turn_index.in_(sorted(needed)),
            )
        )
    ).all()
    return [
        MemoryFragment(
            message_id=row.message_id,
            turn_index=row.turn_index,
            role=row.role,
            content=row.content,
            summary=row.summary or summarize_turn(row.role, row.content),
            score=0.35,
            source="neighbor",
        )
        for row in rows
    ]


async def build_context_bundle(
    db: AsyncSession,
    *,
    session_id: str,
    query: str,
) -> ContextBundle:
    """完整分层召回：Core + Recall + Neighbors。"""
    settings = get_settings()
    if not settings.conversation_memory_enabled:
        return ContextBundle()
    core = await load_recent_core(db, session_id=session_id)
    core_turns = {f.turn_index for f in core}
    recalled = await recall_relevant(
        db, session_id=session_id, query=query, exclude_turns=core_turns
    )
    neighbors = await expand_neighbors(db, session_id=session_id, anchors=recalled)
    # 邻近若与 core 重叠，去掉
    neighbors = [n for n in neighbors if n.turn_index not in core_turns]
    total = await db.scalar(
        select(func.count()).select_from(ConversationMemory).where(
            ConversationMemory.session_id == session_id
        )
    )
    return ContextBundle(
        core=core,
        recalled=recalled,
        neighbors=neighbors,
        archival_count=int(total or 0),
    )
