"""Application：取消 / 恢复 Agent 任务。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import get_engine
from app.graphs.checkpointer import get_latest_checkpoint_info
from app.infrastructure.persistence.uow import SqlAlchemyUnitOfWork
from app.services.agent_persistence import append_task_event
from app.services.agent_runner_service import enqueue_or_run, run_agent_with_persistence


_TERMINAL = {
    "completed",
    "failed",
    "blocked_safety",
    "validation_failed",
    "no_answer",
    "rejected",
    "cancelled",
}


async def cancel_agent_task(
    db: AsyncSession,
    *,
    user_id: int,
    task_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    uow = SqlAlchemyUnitOfWork(db)
    task = await uow.agent_tasks.get(task_id, user_id=user_id)
    if not task:
        return {"error": "NOT_FOUND"}
    if task.status in _TERMINAL:
        return {
            "task_id": task_id,
            "status": task.status,
            "cancelled": False,
            "deduped": True,
            "message": "任务已结束，无需取消",
        }
    if task.status == "awaiting_confirmation":
        # 取消确认中的任务：视为拒绝写库
        base = dict(task.result or {}) if isinstance(task.result, dict) else {}
        base["cancelled"] = True
        base["cancel_reason"] = reason
        await uow.agent_tasks.update_status(task_id, status="cancelled", result=base)
        task.pending_actions = None
        task.completed_at = datetime.now(timezone.utc)
        await append_task_event(
            db,
            task_id=task_id,
            event_type="task_cancelled",
            payload={
                "event": "task_cancelled",
                "task_id": task_id,
                "reason": reason,
                "title": "任务已取消",
                "status": "done",
            },
        )
        await uow.commit()
        return {"task_id": task_id, "status": "cancelled", "cancelled": True, "deduped": False}

    await uow.agent_tasks.update_status(
        task_id,
        status="cancelled",
        result={"cancelled": True, "reason": reason},
    )
    task.completed_at = datetime.now(timezone.utc)
    await append_task_event(
        db,
        task_id=task_id,
        event_type="task_cancelled",
        payload={
            "event": "task_cancelled",
            "task_id": task_id,
            "reason": reason,
            "title": "任务已取消",
            "status": "done",
        },
    )
    await uow.commit()
    return {"task_id": task_id, "status": "cancelled", "cancelled": True, "deduped": False}


async def resume_agent_task(
    db: AsyncSession,
    *,
    user_id: int,
    task_id: str,
    message: str | None,
    checkpoint_id: str | None,
    trace_id: str,
) -> dict[str, Any]:
    uow = SqlAlchemyUnitOfWork(db)
    task = await uow.agent_tasks.get(task_id, user_id=user_id)
    if not task:
        return {"error": "NOT_FOUND"}

    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    ckpt = await get_latest_checkpoint_info(factory, task_id)
    if not ckpt:
        return {"error": "NO_CHECKPOINT"}

    await uow.agent_tasks.update_status(task_id, status="pending")
    task.error_code = None
    task.completed_at = None
    await append_task_event(
        db,
        task_id=task_id,
        event_type="task_resumed",
        payload={
            "event": "task_resumed",
            "task_id": task_id,
            "checkpoint_id": checkpoint_id or ckpt.get("checkpoint_id"),
            "stage": "resume",
            "title": "从检查点恢复",
            "status": "done",
        },
    )
    await uow.commit()

    run_message = message or task.message or ""
    payload = {
        "task_id": task_id,
        "user_id": user_id,
        "message": run_message,
        "session_id": task.session_id,
        "trace_id": trace_id,
        "resume": True,
    }

    async def _runner() -> None:
        await run_agent_with_persistence(
            task_id=task_id,
            user_id=user_id,
            message=run_message,
            session_id=task.session_id,
            trace_id=trace_id,
            trace_name="agent_resume",
            resume=True,
        )

    enqueue_or_run(task_id, payload, _runner)
    return {
        "task_id": task_id,
        "status": "pending",
        "resumed": True,
        "checkpoint_id": checkpoint_id or ckpt.get("checkpoint_id"),
    }
