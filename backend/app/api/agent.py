"""Agent 任务 API：创建任务 + SSE 流式事件（Postgres 持久化）。"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import fail, get_current_user, get_request_id, ok
from app.core.config import get_settings
from app.core.input_sanitizer import get_sanitizer
from app.core.metrics import SANITIZE_REJECT
from app.core.token_monitor import TokenBudgetExceeded
from app.core.tracing import end_trace, get_trace, list_traces, start_trace
from app.db.session import get_db, get_engine
from app.graphs.checkpointer import get_latest_checkpoint_info
from app.graphs.fitness_graph import run_fitness_agent
from app.models.agent_task import AgentTask
from app.models.user import User
from app.schemas.auth_biz import AgentApproveRequest, AgentResumeRequest, AgentTaskCreate
from app.services.agent_persistence import (
    append_task_event,
    list_task_events,
    mark_task_finished,
    mark_task_started,
    save_checkpoint,
)
from app.services.agent_task_finalize import finalize_agent_result

router = APIRouter(prefix="/agent", tags=["agent"])

# 同进程热路径缓冲（与 DB 双写，供低延迟 SSE）
_TASK_EVENTS: dict[str, list[dict[str, Any]]] = {}
_TASK_DONE: dict[str, bool] = {}


def _enqueue_or_run(task_id: str, payload: dict[str, Any], runner_coro_factory) -> None:
    settings = get_settings()
    if settings.agent_use_worker:
        from app.worker.redis_queue import enqueue_agent_task

        async def _enqueue() -> None:
            await enqueue_agent_task(payload)

        asyncio.create_task(_enqueue())
    else:
        asyncio.create_task(runner_coro_factory())


def _sse(event: str, data: dict[str, Any], *, event_id: int | None = None) -> str:
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    lines.append("")
    lines.append("")
    return "\n".join(lines)


def _sanitize_or_fail(rid: str, message: str) -> tuple[str | None, JSONResponse | None]:
    clean, err = get_sanitizer().sanitize(message)
    if err:
        SANITIZE_REJECT.labels(reason="sanitize").inc()
        return None, JSONResponse(
            status_code=400,
            content=fail(rid, "UNSAFE_INPUT", err),
        )
    return clean, None


async def _persist_event(db: AsyncSession, task_id: str, ev: dict[str, Any]) -> int | None:
    event_type = str(ev.get("event") or "progress")
    row = await append_task_event(db, task_id=task_id, event_type=event_type, payload=ev)
    await db.commit()
    return row.seq


@router.post("/chat")
async def chat_legacy(
    body: AgentTaskCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """兼容旧接口：同步跑一轮 Agent。"""
    rid = get_request_id(request)
    clean, bad = _sanitize_or_fail(rid, body.message)
    if bad:
        return bad
    task_id = f"task_{uuid.uuid4().hex[:12]}"
    start_trace("agent_chat", task_id=task_id, user_id=user.id)
    try:
        result = await run_fitness_agent(
            db=db,
            user_id=user.id,
            message=clean or "",
            task_id=task_id,
            session_id=body.session_id,
            trace_id=rid,
        )
        return JSONResponse(
            ok(
                rid,
                {
                    "reply": result.get("reply"),
                    "citations": result.get("citations") or [],
                    "final_status": result.get("final_status"),
                    "pending_actions": result.get("pending_actions"),
                    "requires_confirmation": result.get("requires_confirmation", False),
                    "task_id": task_id,
                },
            )
        )
    except TokenBudgetExceeded as exc:
        return JSONResponse(
            status_code=429,
            content=fail(rid, "TOKEN_BUDGET_EXCEEDED", str(exc), details=exc.snapshot.to_dict()),
        )
    finally:
        await db.commit()
        end_trace()


@router.post("/tasks")
async def create_task(
    body: AgentTaskCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
    rid = get_request_id(request)
    clean, bad = _sanitize_or_fail(rid, body.message)
    if bad:
        return bad
    if idempotency_key:
        existing = await db.scalar(
            select(AgentTask).where(
                AgentTask.user_id == user.id, AgentTask.idempotency_key == idempotency_key
            )
        )
        if existing:
            return JSONResponse(ok(rid, {"task_id": existing.id, "status": existing.status, "deduped": True}))

    task_id = f"task_{uuid.uuid4().hex[:12]}"
    task = AgentTask(
        id=task_id,
        user_id=user.id,
        session_id=body.session_id,
        status="pending",
        message=clean or "",
        idempotency_key=idempotency_key,
        trace_id=rid,
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
    _TASK_EVENTS[task_id] = [started_ev]
    _TASK_DONE[task_id] = False
    await append_task_event(db, task_id=task_id, event_type="task_started", payload=started_ev)
    await db.commit()

    async def _runner() -> None:
        from app.core.progress import reset_progress_sink, set_progress_sink
        from app.db.session import get_engine
        from sqlalchemy.ext.asyncio import async_sessionmaker

        persisted_count = 0

        def _sink(ev: dict[str, Any]) -> None:
            _TASK_EVENTS.setdefault(task_id, []).append(ev)

        async def _persist_loop() -> None:
            nonlocal persisted_count
            while not _TASK_DONE.get(task_id):
                buf = _TASK_EVENTS.get(task_id, [])
                while persisted_count < len(buf):
                    ev = buf[persisted_count]
                    persisted_count += 1
                    async with factory() as ev_db:
                        await _persist_event(ev_db, task_id, ev)
                await asyncio.sleep(0.15)
            buf = _TASK_EVENTS.get(task_id, [])
            while persisted_count < len(buf):
                ev = buf[persisted_count]
                persisted_count += 1
                async with factory() as ev_db:
                    await _persist_event(ev_db, task_id, ev)

        token = set_progress_sink(_sink)
        factory = async_sessionmaker(get_engine(), expire_on_commit=False)
        persist_task = asyncio.create_task(_persist_loop())
        start_trace("agent_task", task_id=task_id, user_id=user.id)
        try:
            async with factory() as session:
                await mark_task_started(session, task_id, trace_id=rid)
                await session.commit()

                result = await run_fitness_agent(
                    db=session,
                    user_id=user.id,
                    message=clean or "",
                    task_id=task_id,
                    session_id=body.session_id,
                    trace_id=rid,
                )
                intents = result.get("intents") or []
                if intents:
                    row = await session.get(AgentTask, task_id)
                    if row:
                        row.intent = str(intents[0])
                        await session.commit()

                buf = _TASK_EVENTS.setdefault(task_id, [])
                await finalize_agent_result(
                    session,
                    task_id=task_id,
                    result=result,
                    persist_event=_persist_event,
                    buffer_events=buf,
                )
        except TokenBudgetExceeded as exc:
            fail_ev = {"event": "failed", "code": "TOKEN_BUDGET_EXCEEDED", "message": str(exc)}
            _TASK_EVENTS.setdefault(task_id, []).append(fail_ev)
            async with factory() as session:
                await _persist_event(session, task_id, fail_ev)
                await mark_task_finished(
                    session, task_id, status="failed", error_code="TOKEN_BUDGET_EXCEEDED"
                )
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            fail_ev = {"event": "failed", "code": "AGENT_ERROR", "message": str(exc)}
            _TASK_EVENTS.setdefault(task_id, []).append(fail_ev)
            async with factory() as session:
                await _persist_event(session, task_id, fail_ev)
                await mark_task_finished(session, task_id, status="failed", error_code="AGENT_ERROR")
                await session.commit()
        finally:
            end_trace()
            reset_progress_sink(token)
            _TASK_DONE[task_id] = True
            await persist_task

    payload = {
        "task_id": task_id,
        "user_id": user.id,
        "message": clean or "",
        "session_id": body.session_id,
        "trace_id": rid,
    }
    _enqueue_or_run(task_id, payload, _runner)
    return JSONResponse(ok(rid, {"task_id": task_id, "status": "pending", "queued": get_settings().agent_use_worker}))


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """查询任务终态（SSE 断线后补查）。"""
    rid = get_request_id(request)
    task = await db.scalar(select(AgentTask).where(AgentTask.id == task_id, AgentTask.user_id == user.id))
    if not task:
        return JSONResponse(status_code=404, content=fail(rid, "NOT_FOUND", "任务不存在"))
    return JSONResponse(
        ok(
            rid,
            {
                "task_id": task.id,
                "status": task.status,
                "intent": task.intent,
                "result": task.result,
                "pending_actions": task.pending_actions,
                "error_code": task.error_code,
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            },
        )
    )


@router.get("/tasks/{task_id}/checkpoint")
async def get_task_checkpoint(
    task_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """查询 LangGraph 最新检查点（用于断点续跑）。"""
    rid = get_request_id(request)
    task = await db.scalar(select(AgentTask).where(AgentTask.id == task_id, AgentTask.user_id == user.id))
    if not task:
        return JSONResponse(status_code=404, content=fail(rid, "NOT_FOUND", "任务不存在"))
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    info = await get_latest_checkpoint_info(factory, task_id)
    if not info:
        return JSONResponse(status_code=404, content=fail(rid, "NO_CHECKPOINT", "无可用检查点"))
    return JSONResponse(
        ok(
            rid,
            {
                "task_id": task_id,
                "checkpoint": info,
                "resumable": task.status in {"running", "failed", "awaiting_confirmation"},
                "awaiting_approval": task.status == "awaiting_confirmation",
            },
        )
    )


@router.post("/tasks/{task_id}/approve")
async def approve_task(
    task_id: str,
    body: AgentApproveRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """LangGraph interrupt 恢复：批准/拒绝计划。"""
    rid = get_request_id(request)
    task = await db.scalar(select(AgentTask).where(AgentTask.id == task_id, AgentTask.user_id == user.id))
    if not task:
        return JSONResponse(status_code=404, content=fail(rid, "NOT_FOUND", "任务不存在"))
    if task.status != "awaiting_confirmation":
        return JSONResponse(status_code=400, content=fail(rid, "NOT_AWAITING", "任务不在等待确认状态"))

    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    task.status = "pending"
    task.error_code = None
    task.completed_at = None
    await db.commit()

    approve_ev = {
        "event": "task_approval",
        "task_id": task_id,
        "approve": body.approve,
        "title": "用户已确认" if body.approve else "用户已拒绝",
        "status": "done",
    }
    _TASK_EVENTS[task_id] = [approve_ev]
    _TASK_DONE[task_id] = False
    await append_task_event(db, task_id=task_id, event_type="task_approval", payload=approve_ev)
    await db.commit()

    resume_command = {"approve": body.approve, "comment": body.comment}

    async def _runner() -> None:
        from app.core.progress import reset_progress_sink, set_progress_sink

        persisted_count = 0

        def _sink(ev: dict[str, Any]) -> None:
            _TASK_EVENTS.setdefault(task_id, []).append(ev)

        async def _persist_loop() -> None:
            nonlocal persisted_count
            while not _TASK_DONE.get(task_id):
                buf = _TASK_EVENTS.get(task_id, [])
                while persisted_count < len(buf):
                    ev = buf[persisted_count]
                    persisted_count += 1
                    async with factory() as ev_db:
                        await _persist_event(ev_db, task_id, ev)
                await asyncio.sleep(0.15)
            buf = _TASK_EVENTS.get(task_id, [])
            while persisted_count < len(buf):
                ev = buf[persisted_count]
                persisted_count += 1
                async with factory() as ev_db:
                    await _persist_event(ev_db, task_id, ev)

        token = set_progress_sink(_sink)
        persist_task = asyncio.create_task(_persist_loop())
        start_trace("agent_approve", task_id=task_id, user_id=user.id)
        try:
            async with factory() as session:
                await mark_task_started(session, task_id, trace_id=rid)
                await session.commit()
                result = await run_fitness_agent(
                    db=session,
                    user_id=user.id,
                    message=task.message or "",
                    task_id=task_id,
                    session_id=task.session_id,
                    trace_id=rid,
                    resume_command=resume_command,
                )
                buf = _TASK_EVENTS.setdefault(task_id, [])
                await finalize_agent_result(
                    session,
                    task_id=task_id,
                    result=result,
                    persist_event=_persist_event,
                    buffer_events=buf,
                )
        except Exception as exc:  # noqa: BLE001
            fail_ev = {"event": "failed", "code": "AGENT_ERROR", "message": str(exc)}
            async with factory() as session:
                await _persist_event(session, task_id, fail_ev)
                await mark_task_finished(session, task_id, status="failed", error_code="AGENT_ERROR")
                await session.commit()
        finally:
            end_trace()
            reset_progress_sink(token)
            _TASK_DONE[task_id] = True
            await persist_task

    _enqueue_or_run(task_id, {"task_id": task_id, "resume_command": resume_command}, _runner)
    return JSONResponse(ok(rid, {"task_id": task_id, "status": "pending", "approved": body.approve}))


@router.post("/tasks/{task_id}/resume")
async def resume_task(
    task_id: str,
    body: AgentResumeRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """从 LangGraph 检查点恢复任务（崩溃/中断后续跑）。"""
    rid = get_request_id(request)
    task = await db.scalar(select(AgentTask).where(AgentTask.id == task_id, AgentTask.user_id == user.id))
    if not task:
        return JSONResponse(status_code=404, content=fail(rid, "NOT_FOUND", "任务不存在"))
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    ckpt = await get_latest_checkpoint_info(factory, task_id)
    if not ckpt:
        return JSONResponse(status_code=404, content=fail(rid, "NO_CHECKPOINT", "无可用检查点"))

    task.status = "pending"
    task.error_code = None
    task.completed_at = None
    await db.commit()

    resume_ev = {
        "event": "task_resumed",
        "task_id": task_id,
        "checkpoint_id": body.checkpoint_id or ckpt.get("checkpoint_id"),
        "stage": "resume",
        "title": "从检查点恢复",
        "status": "done",
    }
    _TASK_EVENTS[task_id] = [resume_ev]
    _TASK_DONE[task_id] = False
    await append_task_event(db, task_id=task_id, event_type="task_resumed", payload=resume_ev)
    await db.commit()

    async def _runner() -> None:
        from app.core.progress import reset_progress_sink, set_progress_sink

        persisted_count = 0

        def _sink(ev: dict[str, Any]) -> None:
            _TASK_EVENTS.setdefault(task_id, []).append(ev)

        async def _persist_loop() -> None:
            nonlocal persisted_count
            while not _TASK_DONE.get(task_id):
                buf = _TASK_EVENTS.get(task_id, [])
                while persisted_count < len(buf):
                    ev = buf[persisted_count]
                    persisted_count += 1
                    async with factory() as ev_db:
                        await _persist_event(ev_db, task_id, ev)
                await asyncio.sleep(0.15)
            buf = _TASK_EVENTS.get(task_id, [])
            while persisted_count < len(buf):
                ev = buf[persisted_count]
                persisted_count += 1
                async with factory() as ev_db:
                    await _persist_event(ev_db, task_id, ev)

        token = set_progress_sink(_sink)
        persist_task = asyncio.create_task(_persist_loop())
        start_trace("agent_resume", task_id=task_id, user_id=user.id)
        try:
            async with factory() as session:
                await mark_task_started(session, task_id, trace_id=rid)
                await session.commit()
                result = await run_fitness_agent(
                    db=session,
                    user_id=user.id,
                    message=body.message or task.message or "",
                    task_id=task_id,
                    session_id=task.session_id,
                    trace_id=rid,
                    resume=True,
                )
                intents = result.get("intents") or []
                if intents:
                    row = await session.get(AgentTask, task_id)
                    if row:
                        row.intent = str(intents[0])
                        await session.commit()
                buf = _TASK_EVENTS.setdefault(task_id, [])
                await finalize_agent_result(
                    session,
                    task_id=task_id,
                    result=result,
                    persist_event=_persist_event,
                    buffer_events=buf,
                )
        except Exception as exc:  # noqa: BLE001
            fail_ev = {"event": "failed", "code": "AGENT_ERROR", "message": str(exc)}
            async with factory() as session:
                await _persist_event(session, task_id, fail_ev)
                await mark_task_finished(session, task_id, status="failed", error_code="AGENT_ERROR")
                await session.commit()
        finally:
            end_trace()
            reset_progress_sink(token)
            _TASK_DONE[task_id] = True
            await persist_task

    payload = {
        "task_id": task_id,
        "user_id": user.id,
        "message": body.message or task.message or "",
        "session_id": task.session_id,
        "trace_id": rid,
        "resume": True,
    }
    _enqueue_or_run(task_id, payload, _runner)
    return JSONResponse(
        ok(
            rid,
            {
                "task_id": task_id,
                "status": "pending",
                "resumed": True,
                "checkpoint_id": body.checkpoint_id or ckpt.get("checkpoint_id"),
            },
        )
    )


@router.get("/traces")
async def agent_traces(
    request: Request,
    limit: int = 20,
    user: User = Depends(get_current_user),
) -> JSONResponse:
    _ = user
    rid = get_request_id(request)
    return JSONResponse(ok(rid, {"items": list_traces(limit=limit)}))


@router.get("/traces/{trace_id}")
async def agent_trace_detail(
    trace_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> JSONResponse:
    _ = user
    rid = get_request_id(request)
    item = get_trace(trace_id)
    if not item:
        return JSONResponse(status_code=404, content=fail(rid, "NOT_FOUND", "trace 不存在"))
    return JSONResponse(ok(rid, item))


@router.get("/tasks/{task_id}/stream")
async def stream_task(
    task_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    rid = get_request_id(request)
    task = await db.scalar(select(AgentTask).where(AgentTask.id == task_id, AgentTask.user_id == user.id))
    if not task:
        return JSONResponse(status_code=404, content=fail(rid, "NOT_FOUND", "任务不存在"))

    after_seq = int(last_event_id or 0)

    async def event_gen() -> AsyncIterator[str]:
        nonlocal after_seq
        heartbeat = 0
        for _ in range(600):
            if await request.is_disconnected():
                break

            rows = await list_task_events(db, task_id, after_seq=after_seq)
            for row in rows:
                after_seq = row.seq
                payload = dict(row.payload)
                payload.setdefault("seq", row.seq)
                yield _sse(row.event_type, payload, event_id=row.seq)

            # 刷新任务状态（终态）
            row = await db.get(AgentTask, task_id)
            done = _TASK_DONE.get(task_id) or (
                row is not None
                and row.status
                in {
                    "completed",
                    "failed",
                    "blocked_safety",
                    "awaiting_confirmation",
                    "validation_failed",
                    "no_answer",
                }
            )
            if done:
                rows = await list_task_events(db, task_id, after_seq=after_seq)
                for r in rows:
                    after_seq = r.seq
                    payload = dict(r.payload)
                    payload.setdefault("seq", r.seq)
                    yield _sse(r.event_type, payload, event_id=r.seq)
                break

            heartbeat += 1
            if heartbeat % 50 == 0:
                yield _sse("heartbeat", {"task_id": task_id})
            await asyncio.sleep(0.3)

    return StreamingResponse(event_gen(), media_type="text/event-stream")
