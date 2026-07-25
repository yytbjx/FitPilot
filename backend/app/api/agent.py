"""Agent 任务 API：创建 / 批准 / 恢复 / SSE（事件权威源为 Postgres）。"""

from __future__ import annotations

import json
import uuid
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.agent import (
    approve_agent_task,
    cancel_agent_task,
    create_agent_task,
    get_agent_task,
    resume_agent_task,
)
from app.api.deps import fail, get_current_user, get_request_id, ok
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
from app.services.agent_persistence import list_task_events
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/agent", tags=["agent"])

_TERMINAL = {
    "completed",
    "failed",
    "blocked_safety",
    "awaiting_confirmation",
    "validation_failed",
    "no_answer",
}


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
        return None, JSONResponse(status_code=400, content=fail(rid, "UNSAFE_INPUT", err))
    return clean, None


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
    data = await create_agent_task(
        db,
        user_id=user.id,
        message=clean or "",
        session_id=body.session_id,
        trace_id=rid,
        idempotency_key=idempotency_key,
    )
    return JSONResponse(ok(rid, data))


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rid = get_request_id(request)
    task = await get_agent_task(db, user_id=user.id, task_id=task_id)
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
                "resumable": task.status in {"running", "failed", "awaiting_confirmation", "queued", "pending"},
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
    """LangGraph interrupt 恢复：批准/拒绝计划（幂等）。"""
    rid = get_request_id(request)
    data = await approve_agent_task(
        db,
        user_id=user.id,
        task_id=task_id,
        approve=body.approve,
        comment=body.comment,
        trace_id=rid,
    )
    if data.get("error") == "NOT_FOUND":
        return JSONResponse(status_code=404, content=fail(rid, "NOT_FOUND", "任务不存在"))
    if data.get("error") == "NOT_AWAITING":
        return JSONResponse(status_code=400, content=fail(rid, "NOT_AWAITING", "任务不在等待确认状态"))
    return JSONResponse(ok(rid, data))


@router.post("/tasks/{task_id}/resume")
async def resume_task(
    task_id: str,
    body: AgentResumeRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rid = get_request_id(request)
    data = await resume_agent_task(
        db,
        user_id=user.id,
        task_id=task_id,
        message=body.message,
        checkpoint_id=body.checkpoint_id,
        trace_id=rid,
    )
    if data.get("error") == "NOT_FOUND":
        return JSONResponse(status_code=404, content=fail(rid, "NOT_FOUND", "任务不存在"))
    if data.get("error") == "NO_CHECKPOINT":
        return JSONResponse(status_code=404, content=fail(rid, "NO_CHECKPOINT", "无可用检查点"))
    return JSONResponse(ok(rid, data))


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    reason: str | None = None,
) -> JSONResponse:
    rid = get_request_id(request)
    data = await cancel_agent_task(db, user_id=user.id, task_id=task_id, reason=reason)
    if data.get("error") == "NOT_FOUND":
        return JSONResponse(status_code=404, content=fail(rid, "NOT_FOUND", "任务不存在"))
    return JSONResponse(ok(rid, data))


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
    """SSE：仅从 agent_task_events 读取，支持 Last-Event-ID 断线续传。"""
    rid = get_request_id(request)
    task = await db.scalar(select(AgentTask).where(AgentTask.id == task_id, AgentTask.user_id == user.id))
    if not task:
        return JSONResponse(status_code=404, content=fail(rid, "NOT_FOUND", "任务不存在"))

    after_seq = int(last_event_id or 0)

    async def event_gen() -> AsyncIterator[str]:
        nonlocal after_seq
        heartbeat = 0
        # 使用独立 session，避免长时间占用请求 session
        factory = async_sessionmaker(get_engine(), expire_on_commit=False)
        for _ in range(600):
            if await request.is_disconnected():
                break
            async with factory() as session:
                rows = await list_task_events(session, task_id, after_seq=after_seq)
                for row in rows:
                    after_seq = row.seq
                    payload = dict(row.payload)
                    payload.setdefault("seq", row.seq)
                    yield _sse(row.event_type, payload, event_id=row.seq)

                row = await session.get(AgentTask, task_id)
                done = row is not None and row.status in _TERMINAL
                if done:
                    rows = await list_task_events(session, task_id, after_seq=after_seq)
                    for r in rows:
                        after_seq = r.seq
                        payload = dict(r.payload)
                        payload.setdefault("seq", r.seq)
                        yield _sse(r.event_type, payload, event_id=r.seq)
                    break

            heartbeat += 1
            if heartbeat % 50 == 0:
                yield _sse("heartbeat", {"task_id": task_id})
            import asyncio

            await asyncio.sleep(0.3)

    return StreamingResponse(event_gen(), media_type="text/event-stream")
