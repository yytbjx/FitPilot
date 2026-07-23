"""Application：提交计划用例（经 Unit of Work）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.persistence.uow import SqlAlchemyUnitOfWork


async def commit_plan_use_case(
    db: AsyncSession,
    *,
    user_id: int,
    pending: dict[str, Any],
    task_id: str | None = None,
) -> dict[str, Any]:
    uow = SqlAlchemyUnitOfWork(db)
    return await uow.commit_plans_with_task(user_id=user_id, pending=pending, task_id=task_id)


async def rollback_workout_plan_use_case(
    db: AsyncSession,
    *,
    user_id: int,
    workout_plan_id: int,
) -> dict[str, Any]:
    uow = SqlAlchemyUnitOfWork(db)
    result = await uow.plans.rollback_workout(user_id, workout_plan_id)
    if result.get("ok"):
        await uow.commit()
    else:
        await uow.rollback()
    return result
