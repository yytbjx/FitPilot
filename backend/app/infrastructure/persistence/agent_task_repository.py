"""Agent 任务 Repository。"""

from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_task import AgentTask


class AgentTaskRepository(Protocol):
    async def get(
        self, task_id: str, user_id: int | None = None, *, for_update: bool = False
    ) -> AgentTask | None: ...

    async def update_status(
        self,
        task_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error_code: str | None = None,
    ) -> AgentTask | None: ...


class SqlAgentTaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    async def get(
        self, task_id: str, user_id: int | None = None, *, for_update: bool = False
    ) -> AgentTask | None:
        stmt = select(AgentTask).where(AgentTask.id == task_id)
        if user_id is not None:
            stmt = stmt.where(AgentTask.user_id == user_id)
        if for_update:
            # 行锁：并发 approve/cancel 串行化，后到请求读到最新状态
            stmt = stmt.with_for_update()
        return await self._db.scalar(stmt)

    async def update_status(
        self,
        task_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error_code: str | None = None,
    ) -> AgentTask | None:
        row = await self._db.get(AgentTask, task_id)
        if not row:
            return None
        row.status = status
        if result is not None:
            row.result = result
        if error_code is not None:
            row.error_code = error_code
        return row
