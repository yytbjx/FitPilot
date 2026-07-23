"""Application：确认记忆并写回用户档案。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.memory.user_memory import ALLOWED_KEYS, confirm_user_memory
from app.models.audit import AuditLog
from app.models.memory import UserMemory
from app.models.user import UserProfile

# 可写回 UserProfile 的键映射
PROFILE_FIELD_MAP: dict[str, str] = {
    "goal": "goal",
    "equipment": "equipment",
    "weekly_sessions": "weekly_sessions",
    "diet_prefs": "diet_prefs",
    "restrictions": "restrictions",
    "experience_level": "experience_level",
}


def _unwrap_value(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value and len(value) == 1:
        return value["value"]
    if isinstance(value, dict) and "value" in value and set(value.keys()) <= {"value", "note", "unit"}:
        return value["value"]
    return value


def _serialize_profile_value(key: str, raw: Any) -> Any:
    if key == "weekly_sessions":
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    if key == "equipment" and isinstance(raw, (list, tuple)):
        return ",".join(str(x) for x in raw)
    if isinstance(raw, (dict, list)):
        import json

        return json.dumps(raw, ensure_ascii=False)
    return raw


async def apply_memory_to_profile(
    db: AsyncSession,
    *,
    user_id: int,
    memory: UserMemory,
    request_id: str | None = None,
) -> dict[str, Any]:
    """将已确认记忆写入 UserProfile（仅白名单字段）。"""
    field = PROFILE_FIELD_MAP.get(memory.key)
    applied: dict[str, Any] = {"key": memory.key, "applied": False}

    if memory.key == "preferred_training_time":
        # 档案无独立字段：追加到 diet_prefs 备注
        field = "diet_prefs"
        raw = _unwrap_value(memory.value)
        profile = await db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
        if profile is None:
            profile = UserProfile(user_id=user_id)
            db.add(profile)
            await db.flush()
        note = f"常用训练时间：{raw}"
        existing = (profile.diet_prefs or "").strip()
        if note not in existing:
            profile.diet_prefs = f"{existing}；{note}".strip("；") if existing else note
        applied = {"key": memory.key, "applied": True, "profile_field": "diet_prefs", "value": profile.diet_prefs}
    elif field:
        raw = _serialize_profile_value(memory.key, _unwrap_value(memory.value))
        if raw is None and memory.key == "weekly_sessions":
            return {"key": memory.key, "applied": False, "error": "INVALID_VALUE"}
        profile = await db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
        if profile is None:
            profile = UserProfile(user_id=user_id)
            db.add(profile)
            await db.flush()
        setattr(profile, field, raw)
        applied = {"key": memory.key, "applied": True, "profile_field": field, "value": raw}
    else:
        # 仅确认记忆，不写档案
        applied = {"key": memory.key, "applied": False, "reason": "NO_PROFILE_FIELD"}

    db.add(
        AuditLog(
            user_id=user_id,
            action="memory_confirm_apply",
            resource_type="user_memory",
            resource_id=str(memory.id),
            detail=applied,
            request_id=request_id,
            message=f"确认记忆 {memory.key} 并尝试写回档案",
        )
    )
    await db.commit()
    return applied


async def confirm_memory_use_case(
    db: AsyncSession,
    *,
    user_id: int,
    memory_id: int,
    apply_to_profile: bool = True,
    request_id: str | None = None,
) -> dict[str, Any]:
    row = await confirm_user_memory(db, user_id=user_id, memory_id=memory_id)
    if not row:
        return {"error": "NOT_FOUND"}
    result: dict[str, Any] = {
        "id": row.id,
        "key": row.key,
        "confirmed": True,
        "value": row.value,
    }
    if apply_to_profile:
        result["profile_writeback"] = await apply_memory_to_profile(
            db, user_id=user_id, memory=row, request_id=request_id
        )
    return result


__all__ = ["confirm_memory_use_case", "apply_memory_to_profile", "PROFILE_FIELD_MAP", "ALLOWED_KEYS"]
