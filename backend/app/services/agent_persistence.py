"""Agent 任务事件持久化（P0：替代纯内存 SSE 缓冲）。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_runtime import AgentTaskEvent
from app.models.agent_task import AgentTask

# 哨兵：区分“调用方未传（不更新该字段）”与“显式传 None（清空该字段）”。
# 用于 S2 修复：commit/reject 后必须能显式清空 DB 中残留的 pending_actions。
_UNSET: Any = object()


async def _next_event_seq(db: AsyncSession, task_id: str) -> int:
    current = await db.scalar(
        select(func.coalesce(func.max(AgentTaskEvent.seq), 0)).where(AgentTaskEvent.task_id == task_id)
    )
    return int(current or 0) + 1


async def append_task_event(
    db: AsyncSession,
    *,
    task_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> AgentTaskEvent:
    """追加任务事件。

    seq 采用 max+1；并发写入撞 (task_id, seq) 唯一约束时（SAVEPOINT 兜底），
    重取 seq 重试一次，仍冲突则抛错由调用方处理。
    """
    seq = await _next_event_seq(db, task_id)
    for _attempt in range(2):
        row = AgentTaskEvent(task_id=task_id, seq=seq, event_type=event_type, payload=payload)
        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
            return row
        except IntegrityError:
            # 并发写同 seq：回滚到保存点后摘除失败行，重取 seq 重试
            try:
                db.expunge(row)
            except Exception:  # noqa: BLE001
                pass
            seq = await _next_event_seq(db, task_id)
    # 理论不可达（第二次失败会直接抛出）；防御性兜底
    raise IntegrityError("INSERT", {}, Exception("agent_task_events seq conflict retry exhausted"))


async def list_task_events(
    db: AsyncSession,
    task_id: str,
    *,
    after_seq: int = 0,
    limit: int = 500,
) -> list[AgentTaskEvent]:
    stmt = (
        select(AgentTaskEvent)
        .where(AgentTaskEvent.task_id == task_id, AgentTaskEvent.seq > after_seq)
        .order_by(AgentTaskEvent.seq)
        .limit(limit)
    )
    return list((await db.scalars(stmt)).all())


async def mark_task_started(
    db: AsyncSession,
    task_id: str,
    *,
    intent: str | None = None,
    trace_id: str | None = None,
) -> None:
    row = await db.get(AgentTask, task_id)
    if not row:
        return
    row.status = "running"
    row.started_at = datetime.now(timezone.utc)
    if intent:
        row.intent = intent
    if trace_id:
        row.trace_id = trace_id
    await db.flush()


async def mark_task_finished(
    db: AsyncSession,
    task_id: str,
    *,
    status: str,
    result: dict[str, Any] | None = None,
    pending_actions: dict[str, Any] | None | object = _UNSET,
    error_code: str | None = None,
) -> None:
    """收尾任务状态。

    pending_actions 语义：
    - 不传（默认 _UNSET）：保持 DB 原值；
    - 传 None：显式清空（commit/reject 后清除残留待确认计划）；
    - 传 dict：覆盖写入。

    取消保护：DB 当前状态已是 cancelled 时，finalize 链不得将其覆盖为
    succeeded/failed 等其他终态（协作式取消兜底）。
    """
    row = await db.get(AgentTask, task_id)
    if not row:
        return
    if row.status == "cancelled" and status != "cancelled":
        return
    row.status = status
    row.completed_at = datetime.now(timezone.utc)
    if result is not None:
        row.result = result
    if pending_actions is not _UNSET:
        row.pending_actions = pending_actions  # type: ignore[assignment]
    if error_code:
        row.error_code = error_code
    await db.flush()
