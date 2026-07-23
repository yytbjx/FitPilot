"""一键演示数据：演示账号 + 档案 + 近两周打卡。

用法:
  cd D:\\FitPilot\\backend
  uv run python ../scripts/seed_demo.py
  uv run python main.py seed-demo
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import hash_password
from app.db.session import get_engine
from app.models.logs import DietLog, WorkoutLog
from app.models.user import User, UserProfile

DEMO_EMAIL = "demo@fitpilot.local"
DEMO_PASSWORD = "demo123456"


async def ensure_demo_user(db: AsyncSession) -> User:
    user = await db.scalar(select(User).where(User.email == DEMO_EMAIL))
    if user is None:
        user = User(email=DEMO_EMAIL, hashed_password=hash_password(DEMO_PASSWORD), role="user")
        db.add(user)
        await db.flush()
    profile = await db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    if profile is None:
        profile = UserProfile(user_id=user.id)
        db.add(profile)
    profile.display_name = "演示用户"
    profile.sex = "male"
    profile.age = 28
    profile.height_cm = 175
    profile.weight_kg = 72
    profile.goal = "fat_loss"
    profile.activity_level = "moderate"
    profile.equipment = "哑铃,杠铃,自重"
    profile.weekly_sessions = 4
    profile.diet_prefs = "高蛋白"
    profile.restrictions = "无海鲜过敏"
    profile.experience_level = "intermediate"
    await db.commit()
    await db.refresh(user)
    return user


async def seed_logs(db: AsyncSession, user_id: int, *, days: int = 14) -> dict[str, int]:
    today = date.today()
    w_created = 0
    d_created = 0
    exercises = [("深蹲", 5, 5, 80.0), ("卧推", 4, 8, 60.0), ("硬拉", 3, 5, 100.0)]
    meals = [
        ("鸡胸肉", 150, 248, 46.5, 0, 5.4),
        ("米饭", 200, 232, 5.2, 51, 0.6),
        ("西兰花", 100, 34, 2.8, 7, 0.4),
    ]
    for i in range(days):
        day = today - timedelta(days=i)
        if i % 2 == 0:
            ex, sets, reps, wt = exercises[i % len(exercises)]
            exists = await db.scalar(
                select(WorkoutLog).where(
                    WorkoutLog.user_id == user_id,
                    WorkoutLog.log_date == day,
                    WorkoutLog.exercise == ex,
                )
            )
            if not exists:
                db.add(
                    WorkoutLog(
                        user_id=user_id,
                        log_date=day,
                        exercise=ex,
                        sets=sets,
                        reps=reps,
                        weight_kg=wt,
                        rpe=7.0,
                        notes="demo",
                    )
                )
                w_created += 1
        food, amount, kcal, protein, carb, fat = meals[i % len(meals)]
        exists_d = await db.scalar(
            select(DietLog).where(
                DietLog.user_id == user_id,
                DietLog.log_date == day,
                DietLog.food_name == food,
            )
        )
        if not exists_d:
            db.add(
                DietLog(
                    user_id=user_id,
                    log_date=day,
                    food_name=food,
                    amount_g=float(amount),
                    meal="lunch",
                    kcal=float(kcal),
                    protein_g=float(protein),
                    carb_g=float(carb),
                    fat_g=float(fat),
                    notes="demo",
                )
            )
            d_created += 1
    await db.commit()
    return {"workout_logs": w_created, "diet_logs": d_created}


async def run_seed_demo() -> dict:
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as db:
        user = await ensure_demo_user(db)
        counts = await seed_logs(db, user.id)
        return {
            "ok": True,
            "email": DEMO_EMAIL,
            "password": DEMO_PASSWORD,
            "user_id": user.id,
            **counts,
            "hint": "登录后可演示：查档案 → 知识问答 → 根据最近两周调整计划 → 确认 Diff",
        }


def main() -> None:
    result = asyncio.run(run_seed_demo())
    import json

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
