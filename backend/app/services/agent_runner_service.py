"""Agent 任务执行辅助：仅将进度事件写入 Postgres（无进程内全局缓冲）。"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Awaitable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.progress import reset_progress_sink, set_progress_sink
from app.core.token_monitor import TokenBudgetExceeded
from app.core.tracing import end_trace, start_trace
from app.db.session import get_engine
from app.graphs.fitness_graph import run_fitness_agent
from app.models.agent_task import AgentTask
from app.services.agent_persistence import (
    append_task_event,
    mark_task_finished,
    mark_task_started,
)
from app.services.agent_task_finalize import finalize_agent_result


async def persist_event(db: AsyncSession, task_id: str, ev: dict[str, Any]) -> int | None:
    event_type = str(ev.get("event") or "progress")
    row = await append_task_event(db, task_id=task_id, event_type=event_type, payload=ev)
    await db.commit()
    return row.seq


async def run_agent_with_persistence(
    *,
    task_id: str,
    user_id: int,
    message: str,
    session_id: str | None,
    trace_id: str | None,
    trace_name: str = "agent_task",
    resume: bool = False,
    resume_command: dict[str, Any] | None = None,
) -> None:
    """在独立 session 中跑 Agent，进度仅落库。"""
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    event_buf: list[dict[str, Any]] = []
    persisted_count = 0
    done = False

    def _sink(ev: dict[str, Any]) -> None:
        event_buf.append(ev)

    async def _persist_loop() -> None:
        nonlocal persisted_count
        while not done:
            while persisted_count < len(event_buf):
                ev = event_buf[persisted_count]
                persisted_count += 1
                async with factory() as ev_db:
                    await persist_event(ev_db, task_id, ev)
            await asyncio.sleep(0.15)
        while persisted_count < len(event_buf):
            ev = event_buf[persisted_count]
            persisted_count += 1
            async with factory() as ev_db:
                await persist_event(ev_db, task_id, ev)

    token = set_progress_sink(_sink)
    persist_task = asyncio.create_task(_persist_loop())
    start_trace(trace_name, task_id=task_id, user_id=user_id)
    try:
        async with factory() as session:
            await mark_task_started(session, task_id, trace_id=trace_id)
            await session.commit()
            result = await run_fitness_agent(
                db=session,
                user_id=user_id,
                message=message,
                task_id=task_id,
                session_id=session_id,
                trace_id=trace_id,
                resume=resume,
                resume_command=resume_command,
            )
            intents = result.get("intents") or []
            if intents:
                row = await session.get(AgentTask, task_id)
                if row:
                    row.intent = str(intents[0])
                    await session.commit()
            await finalize_agent_result(
                session,
                task_id=task_id,
                result=result,
                persist_event=persist_event,
                buffer_events=event_buf,
            )
            # 会话记忆：任务结束后只保留摘要
            if session_id:
                from app.agents.memory import save_session_memory, summarize_session

                payload = {
                    "goal": result.get("current_goal"),
                    "intents": result.get("intents") or [],
                    "pending": bool(result.get("pending_actions")),
                    "risk_level": result.get("risk_level"),
                    "final_status": result.get("final_status"),
                }
                await save_session_memory(
                    session,
                    user_id=user_id,
                    session_id=session_id,
                    task_id=task_id,
                    payload=payload,
                    summary=summarize_session(payload, reply=result.get("reply")),
                )
    except TokenBudgetExceeded as exc:
        fail_ev = {"event": "failed", "code": "TOKEN_BUDGET_EXCEEDED", "message": str(exc)}
        async with factory() as session:
            await persist_event(session, task_id, fail_ev)
            await mark_task_finished(session, task_id, status="failed", error_code="TOKEN_BUDGET_EXCEEDED")
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        fail_ev = {"event": "failed", "code": "AGENT_ERROR", "message": str(exc)}
        async with factory() as session:
            await persist_event(session, task_id, fail_ev)
            await mark_task_finished(session, task_id, status="failed", error_code="AGENT_ERROR")
            await session.commit()
    finally:
        end_trace()
        reset_progress_sink(token)
        done = True
        await persist_task


def enqueue_or_run(task_id: str, payload: dict[str, Any], runner: Callable[[], Awaitable[None]]) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    if settings.agent_use_worker:
        from app.worker.redis_queue import enqueue_agent_task

        async def _enqueue() -> None:
            await enqueue_agent_task(payload)

        asyncio.create_task(_enqueue())
    else:
        asyncio.create_task(runner())
