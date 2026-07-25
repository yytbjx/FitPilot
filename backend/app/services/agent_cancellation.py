"""Agent 任务协作式取消支持（迭代 2）。

三件套：
- AgentTaskCancelledError：图执行途中发现任务已取消时抛出；
- CancellationChecker：带 TTL 的 DB 状态缓存检查器，避免每个 super-step 都打 DB；
- 进程内 asyncio.Task 句柄表：cancel API 先走 task.cancel() 快速路径，
  协作式检查（跨进程 worker 场景的唯一路径）作为兜底。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.models.agent_task import AgentTask

logger = get_logger(__name__)


class AgentTaskCancelledError(Exception):
    """任务在执行中被用户取消（协作式检查或快速路径触发）。"""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(f"agent task cancelled: {task_id}")


# ---------- 进程内任务句柄表（task_id → asyncio.Task） ----------

_running_tasks: dict[str, asyncio.Task[Any]] = {}


def register_task_handle(task_id: str, task: asyncio.Task[Any]) -> None:
    """登记进程内执行任务句柄（仅进程内 asyncio 模式有效）。"""
    _running_tasks[task_id] = task

    def _auto_unregister(done: asyncio.Task[Any]) -> None:
        if _running_tasks.get(task_id) is done:
            _running_tasks.pop(task_id, None)

    task.add_done_callback(_auto_unregister)


def request_fast_cancel(task_id: str) -> bool:
    """尝试 task.cancel() 快速路径；命中返回 True（跨进程时返回 False）。"""
    task = _running_tasks.get(task_id)
    if task is None or task.done():
        return False
    return bool(task.cancel())


# ---------- 协作式取消检查器 ----------

class CancellationChecker:
    """带最小查询间隔的任务取消检查器。

    图逐 super-step 执行时每步调用；距上次 DB 查询不足 interval_seconds
    时直接返回缓存结果，避免高频打库。DB 抖动时不误杀任务（返回 False）。
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        task_id: str,
        *,
        interval_seconds: float = 2.0,
    ) -> None:
        self._factory = session_factory
        self._task_id = task_id
        self._interval = max(0.2, float(interval_seconds))
        self._last_check = 0.0
        self._cancelled = False

    async def __call__(self) -> bool:
        if self._cancelled:
            return True
        now = time.monotonic()
        if now - self._last_check < self._interval:
            return False
        self._last_check = now
        try:
            async with self._factory() as db:
                status = await db.scalar(
                    select(AgentTask.status).where(AgentTask.id == self._task_id)
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("cancel_check_failed task_id=%s err=%s", self._task_id, exc)
            return False
        self._cancelled = status == "cancelled"
        if self._cancelled:
            logger.info("cancel_detected task_id=%s", self._task_id)
        return self._cancelled


CancelCheckerFn = Callable[[], Awaitable[bool]]
