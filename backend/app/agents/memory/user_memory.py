"""用户结构化长期记忆（需确认后才可视为偏好）。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import UserMemory

# 允许的长期记忆键（稳定偏好）
ALLOWED_KEYS = {
    "goal",
    "equipment",
    "weekly_sessions",
    "diet_prefs",
    "restrictions",
    "preferred_training_time",
    "experience_level",
}


async def propose_user_memory(
    db: AsyncSession,
    *,
    user_id: int,
    key: str,
    value: Any,
    source: str = "inferred",
    confidence: float = 0.55,
    notes: str | None = None,
) -> UserMemory | None:
    """提出临时推断；不自动确认，不写档案。"""
    if key not in ALLOWED_KEYS:
        return None
    payload = value if isinstance(value, dict) else {"value": value}
    row = UserMemory(
        user_id=user_id,
        key=key,
        value=payload,
        source=source,
        confidence=max(0.0, min(1.0, float(confidence))),
        requires_confirmation=True,
        confirmed=False,
        notes=notes,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def confirm_user_memory(db: AsyncSession, *, user_id: int, memory_id: int) -> UserMemory | None:
    row = await db.scalar(
        select(UserMemory).where(UserMemory.id == memory_id, UserMemory.user_id == user_id)
    )
    if not row:
        return None
    row.confirmed = True
    row.requires_confirmation = False
    row.confirmed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return row


async def delete_user_memory(db: AsyncSession, *, user_id: int, memory_id: int) -> bool:
    row = await db.scalar(
        select(UserMemory).where(UserMemory.id == memory_id, UserMemory.user_id == user_id)
    )
    if not row:
        return False
    await db.delete(row)
    await db.commit()
    return True


async def list_user_memories(
    db: AsyncSession, *, user_id: int, confirmed_only: bool = False
) -> list[dict[str, Any]]:
    stmt = select(UserMemory).where(UserMemory.user_id == user_id).order_by(UserMemory.id.desc())
    if confirmed_only:
        stmt = stmt.where(UserMemory.confirmed.is_(True))
    rows = list((await db.scalars(stmt)).all())
    return [
        {
            "id": r.id,
            "key": r.key,
            "value": r.value,
            "source": r.source,
            "confidence": r.confidence,
            "confirmed": r.confirmed,
            "requires_confirmation": r.requires_confirmation,
            "confirmed_at": r.confirmed_at.isoformat() if r.confirmed_at else None,
            "notes": r.notes,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


async def confirmed_preferences(db: AsyncSession, *, user_id: int) -> dict[str, Any]:
    """仅返回已确认长期记忆，可安全注入 Agent 上下文。"""
    items = await list_user_memories(db, user_id=user_id, confirmed_only=True)
    out: dict[str, Any] = {}
    for it in items:
        out[it["key"]] = it["value"]
    return out
