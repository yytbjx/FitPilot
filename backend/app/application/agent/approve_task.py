"""Application：批准 / 查询任务。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_task import AgentTask
from app.services.agent_persistence import append_task_event, list_task_events
from app.services.agent_runner_service import enqueue_or_run, run_agent_with_persistence


async def get_agent_task(
    db: AsyncSession, *, user_id: int, task_id: str, for_update: bool = False
) -> AgentTask | None:
    stmt = select(AgentTask).where(AgentTask.id == task_id, AgentTask.user_id == user_id)
    if for_update:
        stmt = stmt.with_for_update()
    return await db.scalar(stmt)


async def approve_agent_task(
    db: AsyncSession,
    *,
    user_id: int,
    task_id: str,
    approve: bool,
    comment: str | None,
    trace_id: str,
) -> dict[str, Any]:
    # SELECT ... FOR UPDATE：并发 approve/cancel 串行化，后到请求读到最新状态（409）
    task = await get_agent_task(db, user_id=user_id, task_id=task_id, for_update=True)
    if not task:
        return {"error": "NOT_FOUND"}

    prev = (task.result or {}) if isinstance(task.result, dict) else {}
    prev_decision = prev.get("approval_decision")
    if task.status != "awaiting_confirmation":
        if prev_decision is not None and bool(prev_decision.get("approve")) == bool(approve):
            return {
                "task_id": task_id,
                "status": task.status,
                "approved": approve,
                "deduped": True,
            }
        return {"error": "NOT_AWAITING"}

    task.status = "pending"
    task.error_code = None
    task.completed_at = None
    base_result = dict(task.result or {}) if isinstance(task.result, dict) else {}
    base_result["approval_decision"] = {
        "approve": approve,
        "comment": comment,
        "request_id": trace_id,
    }
    task.result = base_result
    await db.commit()

    approve_ev = {
        "event": "task_approval",
        "task_id": task_id,
        "approve": approve,
        "title": "用户已确认" if approve else "用户已拒绝",
        "status": "done",
    }
    await append_task_event(db, task_id=task_id, event_type="task_approval", payload=approve_ev)
    await db.commit()

    resume_command = {"approve": approve, "comment": comment}
    payload = {
        "task_id": task_id,
        "user_id": user_id,
        "message": task.message or "",
        "session_id": task.session_id,
        "trace_id": trace_id,
        "resume_command": resume_command,
    }

    async def _runner() -> None:
        await run_agent_with_persistence(
            task_id=task_id,
            user_id=user_id,
            message=task.message or "",
            session_id=task.session_id,
            trace_id=trace_id,
            trace_name="agent_approve",
            resume_command=resume_command,
        )

    enqueue_or_run(task_id, payload, _runner)
    return {"task_id": task_id, "status": "pending", "approved": approve, "deduped": False}


async def list_events(db: AsyncSession, task_id: str, *, after_seq: int = 0):
    return await list_task_events(db, task_id, after_seq=after_seq)
