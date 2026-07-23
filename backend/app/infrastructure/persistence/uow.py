"""Unit of Work：同一事务提交计划 + 审计 + 任务状态。"""

from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.persistence.agent_task_repository import SqlAgentTaskRepository
from app.infrastructure.persistence.plan_repository import SqlPlanRepository
from app.infrastructure.persistence.user_repository import SqlUserRepository


class UnitOfWork(Protocol):
    plans: SqlPlanRepository
    agent_tasks: SqlAgentTaskRepository
    users: SqlUserRepository

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class SqlAlchemyUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.plans = SqlPlanRepository(session)
        self.agent_tasks = SqlAgentTaskRepository(session)
        self.users = SqlUserRepository(session)

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    async def commit_plans_with_task(
        self,
        *,
        user_id: int,
        pending: dict[str, Any],
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """计划版本写入 + 可选任务状态更新，同一事务。"""
        result = await self.plans.commit_pending(user_id, pending)
        if not result.get("ok"):
            await self.rollback()
            return result
        if task_id:
            await self.agent_tasks.update_status(
                task_id,
                status="completed",
                result={"plan_commit": result},
            )
        await self.commit()
        return result
