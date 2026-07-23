"""计划 Repository：隔离 ORM 细节。"""

from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.audit import AuditLog
from app.models.plans import DietPlan, DietPlanVersion, WorkoutPlan, WorkoutPlanVersion


class PlanRepository(Protocol):
    async def get_workout_plan(self, user_id: int, plan_id: int) -> WorkoutPlan | None: ...

    async def get_diet_plan(self, user_id: int, plan_id: int) -> DietPlan | None: ...

    async def commit_pending(self, user_id: int, pending: dict[str, Any]) -> dict[str, Any]: ...

    async def rollback_workout(self, user_id: int, workout_plan_id: int) -> dict[str, Any]: ...


class SqlPlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    async def get_workout_plan(self, user_id: int, plan_id: int) -> WorkoutPlan | None:
        return await self._db.scalar(
            select(WorkoutPlan).where(WorkoutPlan.id == plan_id, WorkoutPlan.user_id == user_id)
        )

    async def get_diet_plan(self, user_id: int, plan_id: int) -> DietPlan | None:
        return await self._db.scalar(
            select(DietPlan).where(DietPlan.id == plan_id, DietPlan.user_id == user_id)
        )

    async def commit_pending(self, user_id: int, pending: dict[str, Any]) -> dict[str, Any]:
        w_id = pending["workout_plan_id"]
        d_id = pending["diet_plan_id"]
        preview = pending["preview"]
        w_plan = await self.get_workout_plan(user_id, w_id)
        d_plan = await self.get_diet_plan(user_id, d_id)
        if not w_plan or not d_plan:
            return {"ok": False, "error": "PLAN_NOT_FOUND"}

        wv = pending["next_workout_version"]
        dv = pending["next_diet_version"]
        self._db.add(
            WorkoutPlanVersion(
                plan_id=w_plan.id,
                version=wv,
                content=preview["workout"],
                change_summary="用户确认提交",
            )
        )
        self._db.add(
            DietPlanVersion(
                plan_id=d_plan.id,
                version=dv,
                content=preview["diet"],
                change_summary="用户确认提交",
            )
        )
        w_plan.current_version = wv
        w_plan.status = "active"
        w_plan.title = preview["workout"]["title"]
        d_plan.current_version = dv
        d_plan.status = "active"
        d_plan.title = preview["diet"]["title"]
        self._db.add(
            AuditLog(
                user_id=user_id,
                action="plan_commit",
                resource_type="workout_plan",
                resource_id=str(w_plan.id),
                detail={"workout_version": wv, "diet_version": dv},
                message="计划已提交",
            )
        )
        return {"ok": True, "workout_version": wv, "diet_version": dv}

    async def rollback_workout(self, user_id: int, workout_plan_id: int) -> dict[str, Any]:
        w_plan = await self._db.scalar(
            select(WorkoutPlan)
            .where(WorkoutPlan.id == workout_plan_id, WorkoutPlan.user_id == user_id)
            .options(selectinload(WorkoutPlan.versions))
        )
        if not w_plan or w_plan.current_version <= 1:
            return {"ok": False, "error": "CANNOT_ROLLBACK"}
        target = w_plan.current_version - 1
        exists = next((v for v in w_plan.versions if v.version == target), None)
        if not exists:
            return {"ok": False, "error": "VERSION_MISSING"}
        w_plan.current_version = target
        self._db.add(
            AuditLog(
                user_id=user_id,
                action="plan_rollback",
                resource_type="workout_plan",
                resource_id=str(w_plan.id),
                detail={"to_version": target},
                message="训练计划回滚",
            )
        )
        return {"ok": True, "current_version": target}
