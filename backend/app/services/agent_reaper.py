"""Stale 任务 reaper + TTL 清理（迭代 2）。

调度：agent_maintenance_loop 同时被 worker 进程（worker 模式）与
FastAPI lifespan（进程内模式）复用；DB 原子 UPDATE ... WHERE status=...
保证多实例并发时不会重复处理同一任务。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import AGENT_CLEANUP_DELETED, AGENT_TASK_REAPED
from app.db.session import get_engine
from app.models.agent_runtime import AgentTaskEvent
from app.models.agent_task import AgentTask
from app.models.langgraph_checkpoint import LGChannelBlob, LGCheckpoint, LGCheckpointWrite
from app.models.memory import UserMemory
from app.services.agent_persistence import append_task_event

logger = get_logger(__name__)

# 仍活跃、不得清理检查点 / 不得 reap 的状态
ACTIVE_STATUSES = ("queued", "pending", "running", "awaiting_confirmation")


# ---------- 纯判定函数（SQL WHERE 的镜像，便于单测） ----------

def is_stale_queued(
    status: str,
    updated_at: datetime,
    *,
    now: datetime,
    stale_seconds: int,
) -> bool:
    """queued 且 updated_at 早于阈值 → 排队超时。"""
    return status == "queued" and updated_at < now - timedelta(seconds=stale_seconds)


def is_stale_running(
    status: str,
    started_at: datetime | None,
    updated_at: datetime,
    *,
    now: datetime,
    running_max_seconds: int,
) -> bool:
    """running 且存活（started_at 优先，回退 updated_at）超过上限 → 运行超时。"""
    if status != "running":
        return False
    anchor = started_at or updated_at
    return anchor < now - timedelta(seconds=running_max_seconds)


# ---------- Stale 任务 reaper ----------

async def reap_stale_tasks(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    stale_seconds: int,
    running_max_seconds: int,
    batch: int = 200,
) -> dict[str, int]:
    """原子化回收 stale 任务；返回 {reason: 处理数}。

    UPDATE ... WHERE status=... RETURNING 保证多实例并发只有一个赢家。
    """
    now = datetime.now(timezone.utc)
    queued_cutoff = now - timedelta(seconds=stale_seconds)
    running_cutoff = now - timedelta(seconds=running_max_seconds)
    out = {"queue_timeout": 0, "running_timeout": 0}

    async with session_factory() as db:
        queued_ids = [
            r[0]
            for r in (
                await db.execute(
                    update(AgentTask)
                    .where(
                        AgentTask.id.in_(
                            select(AgentTask.id)
                            .where(
                                AgentTask.status == "queued",
                                AgentTask.updated_at < queued_cutoff,
                            )
                            .limit(batch)
                        )
                    )
                    .values(status="failed", error_code="queue_timeout", completed_at=now)
                    .returning(AgentTask.id)
                )
            ).all()
        ]
        running_ids = [
            r[0]
            for r in (
                await db.execute(
                    update(AgentTask)
                    .where(
                        AgentTask.id.in_(
                            select(AgentTask.id)
                            .where(
                                AgentTask.status == "running",
                                func.coalesce(AgentTask.started_at, AgentTask.updated_at)
                                < running_cutoff,
                            )
                            .limit(batch)
                        )
                    )
                    .values(status="failed", error_code="running_timeout", completed_at=now)
                    .returning(AgentTask.id)
                )
            ).all()
        ]

        for task_id, reason in [(t, "queue_timeout") for t in queued_ids] + [
            (t, "running_timeout") for t in running_ids
        ]:
            await append_task_event(
                db,
                task_id=task_id,
                event_type="task_failed",
                payload={
                    "event": "failed",
                    "task_id": task_id,
                    "code": reason,
                    "message": "排队超时，任务被回收" if reason == "queue_timeout" else "运行超时，任务被回收",
                    "reaped": True,
                },
            )
        await db.commit()

    for ids, reason in ((queued_ids, "queue_timeout"), (running_ids, "running_timeout")):
        if ids:
            AGENT_TASK_REAPED.labels(reason=reason).inc(len(ids))
            out[reason] = len(ids)
            logger.info("agent_tasks_reaped reason=%s count=%d ids=%s", reason, len(ids), ids[:5])
    return out


# ---------- TTL 清理 ----------

async def _delete_batches(
    db: AsyncSession,
    model: Any,
    id_column: Any,
    where: Any,
    *,
    batch: int,
) -> int:
    """按主键分批 DELETE，避免长事务；返回删除总数。"""
    total = 0
    while True:
        res = await db.execute(
            delete(model).where(
                id_column.in_(select(id_column).where(where).limit(batch))
            )
        )
        await db.commit()
        n = int(res.rowcount or 0)
        total += n
        if n < batch:
            return total


async def cleanup_expired_data(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    retention_days: int,
    event_retention_days: int,
    memory_proposal_ttl_days: int,
    batch: int = 500,
) -> dict[str, int]:
    """删除过期检查点 / 任务事件 / 未确认记忆提议；返回 {kind: 删除数}。"""
    now = datetime.now(timezone.utc)
    ck_cutoff = now - timedelta(days=retention_days)
    ev_cutoff = now - timedelta(days=event_retention_days)
    mem_cutoff = now - timedelta(days=memory_proposal_ttl_days)
    out = {"lg_checkpoints": 0, "agent_task_events": 0, "user_memories": 0}

    async with session_factory() as db:
        # 1) 过期 LangGraph 检查点：仅清理不再活跃的任务线程（保护 awaiting_confirmation resume）
        while True:
            thread_ids = [
                r[0]
                for r in (
                    await db.execute(
                        select(LGCheckpoint.thread_id)
                        .where(
                            LGCheckpoint.created_at < ck_cutoff,
                            LGCheckpoint.thread_id.notin_(
                                select(AgentTask.id).where(AgentTask.status.in_(ACTIVE_STATUSES))
                            ),
                        )
                        .distinct()
                        .limit(batch)
                    )
                ).all()
            ]
            if not thread_ids:
                break
            # 关联表无外键约束；按逻辑依赖顺序删除：writes → blobs → checkpoints
            await db.execute(
                delete(LGCheckpointWrite).where(LGCheckpointWrite.thread_id.in_(thread_ids))
            )
            await db.execute(
                delete(LGChannelBlob).where(LGChannelBlob.thread_id.in_(thread_ids))
            )
            res = await db.execute(
                delete(LGCheckpoint).where(LGCheckpoint.thread_id.in_(thread_ids))
            )
            await db.commit()
            n = int(res.rowcount or 0)
            out["lg_checkpoints"] += n
            if len(thread_ids) < batch:
                break

        # 2) 过期任务事件
        out["agent_task_events"] = await _delete_batches(
            db,
            AgentTaskEvent,
            AgentTaskEvent.id,
            AgentTaskEvent.created_at < ev_cutoff,
            batch=batch,
        )

        # 3) 超期未确认的记忆提议
        out["user_memories"] = await _delete_batches(
            db,
            UserMemory,
            UserMemory.id,
            (UserMemory.confirmed.is_(False)) & (UserMemory.created_at < mem_cutoff),
            batch=batch,
        )

    for kind, n in out.items():
        if n:
            AGENT_CLEANUP_DELETED.labels(kind=kind).inc(n)
            logger.info("agent_cleanup kind=%s deleted=%d", kind, n)
    return out


# ---------- 共用调度循环 ----------

async def agent_maintenance_loop(
    *,
    stop_event: asyncio.Event,
    reaper_interval_seconds: int | None = None,
    cleanup_interval_seconds: int | None = None,
) -> None:
    """reaper + TTL 清理共用调度循环（worker / FastAPI lifespan 复用）。"""
    settings = get_settings()
    reaper_interval = reaper_interval_seconds or settings.agent_reaper_interval_seconds
    cleanup_interval = cleanup_interval_seconds or settings.agent_cleanup_interval_seconds
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    logger.info(
        "agent_maintenance_started reaper_interval=%ds cleanup_interval=%ds",
        reaper_interval,
        cleanup_interval,
    )
    last_cleanup = 0.0
    while not stop_event.is_set():
        try:
            await reap_stale_tasks(
                factory,
                stale_seconds=settings.agent_stale_task_seconds,
                running_max_seconds=settings.agent_running_task_max_seconds,
                batch=settings.agent_cleanup_batch_size,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("agent_reaper_failed: %s", exc)

        now_mono = asyncio.get_running_loop().time()
        if now_mono - last_cleanup >= cleanup_interval:
            try:
                await cleanup_expired_data(
                    factory,
                    retention_days=settings.agent_retention_days,
                    event_retention_days=settings.agent_event_retention_days,
                    memory_proposal_ttl_days=settings.memory_proposal_ttl_days,
                    batch=settings.agent_cleanup_batch_size,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("agent_cleanup_failed: %s", exc)
            last_cleanup = now_mono

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=reaper_interval)
        except asyncio.TimeoutError:
            pass
    logger.info("agent_maintenance_stopped")
