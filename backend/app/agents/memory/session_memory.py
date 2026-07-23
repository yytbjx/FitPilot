"""会话短期记忆（任务级，结束后压缩为摘要）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import SessionMemory


async def load_session_memory(
    db: AsyncSession, *, user_id: int, session_id: str
) -> dict[str, Any] | None:
    row = await db.scalar(
        select(SessionMemory)
        .where(SessionMemory.user_id == user_id, SessionMemory.session_id == session_id)
        .order_by(SessionMemory.id.desc())
    )
    if not row:
        return None
    return {
        "id": row.id,
        "session_id": row.session_id,
        "task_id": row.task_id,
        "summary": row.summary,
        "payload": row.payload or {},
    }


async def save_session_memory(
    db: AsyncSession,
    *,
    user_id: int,
    session_id: str,
    task_id: str | None = None,
    payload: dict[str, Any] | None = None,
    summary: str | None = None,
) -> SessionMemory:
    row = await db.scalar(
        select(SessionMemory).where(
            SessionMemory.user_id == user_id, SessionMemory.session_id == session_id
        )
    )
    data = payload or {}
    if row is None:
        row = SessionMemory(
            user_id=user_id,
            session_id=session_id,
            task_id=task_id,
            payload=data,
            summary=summary,
        )
        db.add(row)
    else:
        merged = dict(row.payload or {})
        merged.update(data)
        row.payload = merged
        if task_id:
            row.task_id = task_id
        if summary is not None:
            row.summary = summary
    await db.commit()
    await db.refresh(row)
    return row


def summarize_session(payload: dict[str, Any], *, reply: str | None = None) -> str:
    """确定性摘要（不调用 LLM）：目标 / 意图 / 是否待确认。"""
    parts: list[str] = []
    if payload.get("goal"):
        parts.append(f"目标：{payload['goal']}")
    intents = payload.get("intents") or []
    if intents:
        parts.append(f"意图：{','.join(str(x) for x in intents)}")
    if payload.get("pending"):
        parts.append("有待确认计划")
    if payload.get("risk_level") == "high":
        parts.append("曾触发安全拦截")
    if reply:
        parts.append(f"末次回复摘要：{(reply or '')[:80]}")
    return "；".join(parts) or "会话无关键结构化摘要"
