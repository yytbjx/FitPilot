"""Application：创建 Agent 任务用例。"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.agent_task import AgentTask
from app.services.agent_persistence import append_task_event
from app.services.agent_runner_service import enqueue_or_run, run_agent_with_persistence


async def create_agent_task(
    db: AsyncSession,
    *,
    user_id: int,
    message: str,
    session_id: str | None,
    trace_id: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    if idempotency_key:
        existing = await db.scalar(
            select(AgentTask).where(
                AgentTask.user_id == user_id, AgentTask.idempotency_key == idempotency_key
            )
        )
        if existing:
            return {"task_id": existing.id, "status": existing.status, "deduped": True}

    task_id = f"task_{uuid.uuid4().hex[:12]}"
    queued = get_settings().agent_use_worker
    task = AgentTask(
        id=task_id,
        user_id=user_id,
        session_id=session_id,
        status="queued" if queued else "pending",
        message=message,
        idempotency_key=idempotency_key,
        trace_id=trace_id,
    )
    db.add(task)
    await db.commit()

    started_ev = {
        "event": "task_started",
        "task_id": task_id,
        "stage": "task_started",
        "title": "任务已创建",
        "detail": "等待 Agent 开始执行",
        "status": "done",
    }
    await append_task_event(db, task_id=task_id, event_type="task_started", payload=started_ev)
    await db.commit()

    payload = {
        "task_id": task_id,
        "user_id": user_id,
        "message": message,
        "session_id": session_id,
        "trace_id": trace_id,
    }

    async def _runner() -> None:
        await run_agent_with_persistence(
            task_id=task_id,
            user_id=user_id,
            message=message,
            session_id=session_id,
            trace_id=trace_id,
            trace_name="agent_task",
        )

    enqueue_or_run(task_id, payload, _runner)
    return {"task_id": task_id, "status": task.status, "queued": queued, "deduped": False}
