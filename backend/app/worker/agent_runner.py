"""独立 Worker：消费 Redis Streams 并执行 Agent 任务（支持优雅退出）。"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
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
from app.worker.redis_queue import (
    ack_agent_task,
    dequeue_agent_task,
    fail_agent_task,
)

logger = logging.getLogger(__name__)

_shutdown = asyncio.Event()


def request_shutdown(*_args: object) -> None:
    _shutdown.set()


async def _persist_event(db, task_id: str, ev: dict[str, Any]) -> None:
    await append_task_event(db, task_id=task_id, event_type=str(ev.get("event") or "progress"), payload=ev)
    await db.commit()


async def run_agent_job(payload: dict[str, Any]) -> None:
    task_id = str(payload["task_id"])
    user_id = int(payload["user_id"])
    message = str(payload.get("message") or "")
    session_id = payload.get("session_id")
    trace_id = payload.get("trace_id")
    stream_id = str(payload.get("_stream_id") or "")

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
                    await _persist_event(ev_db, task_id, ev)
            await asyncio.sleep(0.15)
        while persisted_count < len(event_buf):
            ev = event_buf[persisted_count]
            persisted_count += 1
            async with factory() as ev_db:
                await _persist_event(ev_db, task_id, ev)

    token = set_progress_sink(_sink)
    persist_task = asyncio.create_task(_persist_loop())
    start_trace("agent_worker", task_id=task_id, user_id=user_id)
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
                resume=bool(payload.get("resume")),
                resume_command=payload.get("resume_command"),
            )

            intents = result.get("intents") or []
            if intents:
                row = await session.get(AgentTask, task_id)
                if row:
                    row.intent = str(intents[0])
                    await session.commit()

            from app.services.agent_task_finalize import finalize_agent_result

            async def _persist(ev_db, tid: str, ev: dict[str, Any]) -> None:
                await _persist_event(ev_db, tid, ev)

            await finalize_agent_result(
                session,
                task_id=task_id,
                result=result,
                persist_event=_persist,
                buffer_events=event_buf,
            )
        await ack_agent_task(stream_id)

    except TokenBudgetExceeded as exc:
        async with factory() as session:
            await _persist_event(
                session,
                task_id,
                {"event": "failed", "code": "TOKEN_BUDGET_EXCEEDED", "message": str(exc)},
            )
            await mark_task_finished(session, task_id, status="failed", error_code="TOKEN_BUDGET_EXCEEDED")
            await session.commit()
        await ack_agent_task(stream_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("agent_worker_failed task_id=%s", task_id)
        action = await fail_agent_task(payload, error=str(exc))
        async with factory() as session:
            await _persist_event(
                session,
                task_id,
                {
                    "event": "failed" if action == "dead_letter" else "retrying",
                    "code": "AGENT_ERROR",
                    "message": str(exc),
                    "queue_action": action,
                },
            )
            if action == "dead_letter":
                await mark_task_finished(session, task_id, status="failed", error_code="AGENT_ERROR")
            await session.commit()
    finally:
        done = True
        reset_progress_sink(token)
        await persist_task
        end_trace()


async def worker_loop(*, poll_timeout: int = 5) -> None:
    consumer = f"worker-{os.getpid()}"
    logger.info("FitPilot agent worker started consumer=%s", consumer)
    while not _shutdown.is_set():
        try:
            payload = await dequeue_agent_task(consumer=consumer, timeout=poll_timeout)
        except Exception as exc:  # noqa: BLE001
            logger.warning("dequeue_failed: %s", exc)
            await asyncio.sleep(1)
            continue
        if not payload:
            continue
        if payload.get("_dead_letter"):
            await fail_agent_task(payload, error="max_retries_exceeded")
            continue
        await run_agent_job(payload)
    logger.info("FitPilot agent worker stopped gracefully")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_shutdown)
        except NotImplementedError:
            signal.signal(sig, lambda *_: request_shutdown())
    try:
        loop.run_until_complete(worker_loop())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
