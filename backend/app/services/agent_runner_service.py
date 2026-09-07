"""Agent 任务执行辅助：仅将进度事件写入 Postgres（无进程内全局缓冲）。"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Awaitable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.metrics import AGENT_TASK_TIMEOUT
from app.core.progress import reset_progress_sink, set_progress_sink
from app.core.token_monitor import (
    TokenBudgetExceeded,
    reset_token_budget_user,
    set_token_budget_user,
)
from app.core.tracing import end_trace, start_trace
from app.db.session import get_engine
from app.graphs.fitness_graph import run_fitness_agent
from app.models.agent_task import AgentTask
from app.services.agent_cancellation import (
    AgentTaskCancelledError,
    CancellationChecker,
    register_task_handle,
)
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
    budget_token = set_token_budget_user(user_id)
    persist_task = asyncio.create_task(_persist_loop())
    start_trace(trace_name, task_id=task_id, user_id=user_id)
    settings = get_settings()
    checker = CancellationChecker(factory, task_id)
    try:
        async with factory() as session:
            await mark_task_started(session, task_id, trace_id=trace_id)
            await session.commit()
            try:
                result = await asyncio.wait_for(
                    run_fitness_agent(
                        db=session,
                        user_id=user_id,
                        message=message,
                        task_id=task_id,
                        session_id=session_id,
                        trace_id=trace_id,
                        resume=resume,
                        resume_command=resume_command,
                        cancel_checker=checker,
                    ),
                    timeout=settings.agent_task_timeout_seconds,
                )
            except asyncio.TimeoutError:
                # 任务级超时：明确标记 failed(reason=timeout)，不是静默断
                await session.rollback()
                AGENT_TASK_TIMEOUT.labels(path="inprocess").inc()
                timeout_ev = {
                    "event": "failed",
                    "code": "TASK_TIMEOUT",
                    "message": f"任务执行超过 {settings.agent_task_timeout_seconds}s，已终止",
                }
                await persist_event(session, task_id, timeout_ev)
                await mark_task_finished(session, task_id, status="failed", error_code="timeout")
                await session.commit()
                return
            except AgentTaskCancelledError:
                # 协作式取消：DB 已由 cancel API 置为 cancelled，仅确认终态
                await session.rollback()
                await mark_task_finished(session, task_id, status="cancelled")
                await session.commit()
                return
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
                # 分层对话记忆：归档本轮 user/assistant（摘要+向量）
                if get_settings().conversation_memory_enabled and not resume:
                    from app.agents.memory.conversation_memory import append_message

                    try:
                        await append_message(
                            session,
                            user_id=user_id,
                            session_id=session_id,
                            role="user",
                            content=message,
                            task_id=task_id,
                            extra={"intents": result.get("intents") or []},
                        )
                        reply_text = (result.get("reply") or "").strip()
                        if reply_text:
                            await append_message(
                                session,
                                user_id=user_id,
                                session_id=session_id,
                                role="assistant",
                                content=reply_text,
                                task_id=task_id,
                                extra={"final_status": result.get("final_status")},
                            )
                    except Exception:  # noqa: BLE001 — 记忆写入失败不阻断任务终态
                        pass
    except TokenBudgetExceeded as exc:
        fail_ev = {"event": "failed", "code": "TOKEN_BUDGET_EXCEEDED", "message": str(exc)}
        async with factory() as session:
            await persist_event(session, task_id, fail_ev)
            await mark_task_finished(session, task_id, status="failed", error_code="TOKEN_BUDGET_EXCEEDED")
            await session.commit()
    except asyncio.CancelledError:
        # 快速路径 task.cancel()：DB 已由 cancel API 置 cancelled，尽力确认终态后向上抛
        try:
            async with factory() as session:
                await mark_task_finished(session, task_id, status="cancelled")
                await session.commit()
        finally:
            raise
    except Exception as exc:  # noqa: BLE001
        fail_ev = {"event": "failed", "code": "AGENT_ERROR", "message": str(exc)}
        async with factory() as session:
            await persist_event(session, task_id, fail_ev)
            await mark_task_finished(session, task_id, status="failed", error_code="AGENT_ERROR")
            await session.commit()
    finally:
        end_trace()
        reset_progress_sink(token)
        reset_token_budget_user(budget_token)
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
        # 进程内模式：登记 task_id→Task 句柄，cancel 可走 task.cancel() 快速路径
        task = asyncio.create_task(runner())
        register_task_handle(task_id, task)
