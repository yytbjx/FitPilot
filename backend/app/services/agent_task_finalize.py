"""Agent 任务终态处理（含 LangGraph interrupt）。"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.graphs.runner_utils import approval_events_from_result
from app.services.agent_persistence import mark_task_finished


PersistFn = Callable[[AsyncSession, str, dict[str, Any]], Awaitable[None]]


async def finalize_agent_result(
    session: AsyncSession,
    *,
    task_id: str,
    result: dict[str, Any],
    persist_event: PersistFn,
    buffer_events: list[dict[str, Any]] | None = None,
) -> str:
    """持久化事件并更新任务状态。返回最终 status。"""
    buf = buffer_events if buffer_events is not None else []

    for ev in approval_events_from_result(result):
        if not any(e.get("event") == ev.get("event") for e in buf):
            buf.append(ev)
        await persist_event(session, task_id, ev)

    for ev in result.get("events") or []:
        if ev.get("event") in {"completed", "failed", "approval_required", "node_started", "approval_decision"}:
            if ev.get("event") == "completed":
                ev = {
                    **ev,
                    "reply": ev.get("reply") or result.get("reply"),
                    "citations": ev.get("citations") or result.get("citations") or [],
                    "final_status": ev.get("final_status") or result.get("final_status"),
                    "retrieved_evidence": ev.get("retrieved_evidence") or result.get("retrieved_evidence"),
                }
            if not any(
                e.get("event") == ev.get("event") and e.get("status") == ev.get("status") for e in buf
            ):
                buf.append(ev)
            await persist_event(session, task_id, ev)

    # 检查点由 LangGraph PostgresCheckpointSaver（graphs/checkpointer.py）负责；
    # 此处不再写自研 agent_checkpoints 冗余表。
    await session.commit()

    if result.get("interrupted"):
        final_status = "awaiting_confirmation"
        await mark_task_finished(
            session,
            task_id,
            status=final_status,
            result={"reply": result.get("reply"), "final_status": final_status},
            pending_actions=result.get("pending_actions"),
        )
        await session.commit()
        return final_status

    final_status = str(result.get("final_status") or "completed")
    if not any(e.get("event") == "completed" for e in buf):
        if not any(e.get("event") == "approval_required" for e in buf):
            done_ev = {
                "event": "completed",
                "reply": result.get("reply"),
                "citations": result.get("citations") or [],
                "final_status": final_status,
                "pending_actions": result.get("pending_actions"),
            }
            buf.append(done_ev)
            await persist_event(session, task_id, done_ev)

    await mark_task_finished(
        session,
        task_id,
        status=final_status,
        result={
            "reply": result.get("reply"),
            "citations": result.get("citations"),
            "final_status": final_status,
        },
        pending_actions=result.get("pending_actions"),
    )
    await session.commit()
    return final_status
