"""用户档案与日志 Repository。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.body import BodyMetric
from app.models.logs import DietLog, WorkoutLog
from app.models.user import UserProfile
from app.services.nutrition import estimate_tdee, target_macros_for_goal
from app.services.training_load import SetVolume, weekly_volume


class UserRepository(Protocol):
    async def get_profile_dict(self, user_id: int) -> dict[str, Any]: ...

    async def recent_logs(self, user_id: int, *, days: int = 7) -> dict[str, Any]: ...


class SqlUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    async def get_profile_dict(self, user_id: int) -> dict[str, Any]:
        profile = await self._db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
        if not profile:
            return {}
        data = {
            "display_name": profile.display_name,
            "sex": profile.sex,
            "age": profile.age,
            "height_cm": profile.height_cm,
            "weight_kg": profile.weight_kg,
            "goal": profile.goal,
            "activity_level": profile.activity_level,
            "equipment": profile.equipment,
            "injuries": profile.injuries,
            "restrictions": profile.restrictions,
            "weekly_sessions": profile.weekly_sessions,
        }
        if profile.weight_kg and profile.height_cm and profile.age:
            energy = estimate_tdee(
                sex=profile.sex,
                weight_kg=profile.weight_kg,
                height_cm=profile.height_cm,
                age=profile.age,
                activity_level=profile.activity_level,
            )
            data["nutrition_estimate"] = {
                **energy,
                "targets": target_macros_for_goal(energy["tdee"], profile.goal, profile.weight_kg),
            }
        return data

    async def recent_logs(self, user_id: int, *, days: int = 7) -> dict[str, Any]:
        since = date.today() - timedelta(days=days)
        workouts = (
            await self._db.scalars(
                select(WorkoutLog).where(WorkoutLog.user_id == user_id, WorkoutLog.log_date >= since)
            )
        ).all()
        diets = (
            await self._db.scalars(
                select(DietLog).where(DietLog.user_id == user_id, DietLog.log_date >= since)
            )
        ).all()
        bodies = (
            await self._db.scalars(
                select(BodyMetric)
                .where(BodyMetric.user_id == user_id)
                .order_by(BodyMetric.log_date.desc())
                .limit(10)
            )
        ).all()
        volumes = weekly_volume(
            [
                SetVolume(
                    exercise=w.exercise,
                    sets=w.sets or 0,
                    reps=w.reps or 0,
                    weight_kg=w.weight_kg or 0,
                )
                for w in workouts
                if w.sets and w.reps
            ]
        )
        return {
            "days": days,
            "workout_count": len(workouts),
            "volume": volumes,
            "diet_kcal": round(sum(d.kcal for d in diets), 1),
            "diet_protein_g": round(sum(d.protein_g for d in diets), 1),
            "body_metrics": [
                {
                    "date": b.log_date.isoformat(),
                    "weight_kg": b.weight_kg,
                    "body_fat_pct": b.body_fat_pct,
                }
                for b in bodies
            ],
        }
