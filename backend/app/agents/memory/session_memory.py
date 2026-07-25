"""会话短期记忆（任务级，结束后压缩为摘要）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import SessionMemory


async def load_session_memory(
    db: AsyncSession, *, user_id: int, session_id: str
) -> dict[str, Any] | None:
    # (user_id, session_id) 已有唯一约束，最多一行，无需再按 id 排序取最新
    row = await db.scalar(
        select(SessionMemory).where(
            SessionMemory.user_id == user_id, SessionMemory.session_id == session_id
        )
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
    """insert ... on conflict upsert：并发安全（S4 修复），payload 按键合并。"""
    data = payload or {}
    stmt = pg_insert(SessionMemory).values(
        user_id=user_id,
        session_id=session_id,
        task_id=task_id,
        payload=data,
        summary=summary,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "session_id"],
        set_={
            # 仅在调用方提供新值时覆盖，否则保留原值
            "task_id": func.coalesce(stmt.excluded.task_id, SessionMemory.task_id),
            "summary": func.coalesce(stmt.excluded.summary, SessionMemory.summary),
            # jsonb || 顶层键合并（新值覆盖同名旧键），与原 read-merge-write 语义一致
            "payload": cast(SessionMemory.payload, JSONB).concat(cast(data, JSONB)),
            "updated_at": func.now(),
        },
    )
    await db.execute(stmt)
    row = await db.scalar(
        select(SessionMemory).where(
            SessionMemory.user_id == user_id, SessionMemory.session_id == session_id
        )
    )
    await db.commit()
    assert row is not None  # upsert 成功后必存在
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
