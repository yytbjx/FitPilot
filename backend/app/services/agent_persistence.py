"""Agent 任务事件与检查点持久化（P0：替代纯内存 SSE 缓冲）。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_runtime import AgentCheckpoint, AgentTaskEvent, AgentTaskStep, AgentToolCall
from app.models.agent_task import AgentTask


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
    seq = await _next_event_seq(db, task_id)
    row = AgentTaskEvent(task_id=task_id, seq=seq, event_type=event_type, payload=payload)
    db.add(row)
    await db.flush()
    return row


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
    pending_actions: dict[str, Any] | None = None,
    error_code: str | None = None,
) -> None:
    row = await db.get(AgentTask, task_id)
    if not row:
        return
    row.status = status
    row.completed_at = datetime.now(timezone.utc)
    if result is not None:
        row.result = result
    if pending_actions is not None:
        row.pending_actions = pending_actions
    if error_code:
        row.error_code = error_code
    await db.flush()


async def upsert_task_step(
    db: AsyncSession,
    *,
    task_id: str,
    step_name: str,
    title: str,
    status: str,
    detail: str | None = None,
    ended: bool = False,
) -> None:
    row = await db.scalar(
        select(AgentTaskStep)
        .where(AgentTaskStep.task_id == task_id, AgentTaskStep.step_name == step_name)
        .order_by(AgentTaskStep.id.desc())
        .limit(1)
    )
    if row is None or ended:
        row = AgentTaskStep(
            task_id=task_id,
            step_name=step_name,
            title=title,
            status=status,
            detail=detail,
        )
        db.add(row)
    else:
        row.status = status
        row.detail = detail
        if ended:
            row.ended_at = datetime.now(timezone.utc)
    task = await db.get(AgentTask, task_id)
    if task:
        task.current_step = step_name
    await db.flush()


async def record_tool_call(
    db: AsyncSession,
    *,
    task_id: str,
    tool_name: str,
    input_json: dict[str, Any] | None,
    output_json: dict[str, Any] | None,
    status: str = "ok",
    error_code: str | None = None,
) -> None:
    db.add(
        AgentToolCall(
            task_id=task_id,
            tool_name=tool_name,
            input_json=input_json,
            output_json=output_json,
            status=status,
            error_code=error_code,
        )
    )
    await db.flush()


async def save_checkpoint(
    db: AsyncSession,
    *,
    task_id: str,
    node_name: str,
    state: dict[str, Any],
) -> None:
    db.add(AgentCheckpoint(task_id=task_id, node_name=node_name, state_json=state))
    await db.flush()
