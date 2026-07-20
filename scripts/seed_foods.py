"""写入中文种子食物 + USDA Foundation Foods（幂等）。

用法:
  cd D:\\FitPilot
  $env:PYTHONPATH=\"D:\\FitPilot\\backend\"
  .\\backend\\.venv\\Scripts\\python.exe scripts\\seed_foods.py
  .\\backend\\.venv\\Scripts\\python.exe scripts\\seed_foods.py --usda-only
  .\\backend\\.venv\\Scripts\\python.exe scripts\\seed_foods.py --limit 50
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import get_engine
from app.models.food import FoodItem
from app.services.food_fdc import default_macros_path, load_foundation_foods, upsert_foods
from app.services.food_seed import SEED_FOODS


async def seed_manual(db: AsyncSession) -> int:
    created = 0
    for item in SEED_FOODS:
        exists = await db.scalar(select(FoodItem).where(FoodItem.name == item["name"]))
        if exists:
            # 确保中文种子有 source=manual
            if not exists.source:
                exists.source = "manual"
            continue
        db.add(
            FoodItem(
                source="manual",
                external_id=None,
                name=item["name"],
                category=item.get("category"),
                serving_g=100.0,
                kcal_per_100g=item["kcal_per_100g"],
                protein_g_per_100g=item["protein_g_per_100g"],
                carb_g_per_100g=item["carb_g_per_100g"],
                fat_g_per_100g=item["fat_g_per_100g"],
            )
        )
        created += 1
    await db.commit()
    return created


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed FitPilot foods")
    parser.add_argument("--usda-only", action="store_true", help="跳过中文种子")
    parser.add_argument("--skip-usda", action="store_true", help="只写中文种子")
    parser.add_argument("--limit", type=int, default=None, help="仅导入前 N 条 USDA（调试）")
    args = parser.parse_args()

    engine = get_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:  # type: AsyncSession
        if not args.usda_only:
            n = await seed_manual(db)
            print(f"manual_seeded={n}")

        if not args.skip_usda:
            rows = load_foundation_foods()
            if args.limit:
                rows = rows[: args.limit]
            result = await upsert_foods(db, rows)
            print("usda:", result, "source_file=", default_macros_path())

        total = await db.scalar(select(func.count()).select_from(FoodItem))
        by_src = (
            await db.execute(
                select(FoodItem.source, func.count()).group_by(FoodItem.source)
            )
        ).all()
        print("food_total", int(total or 0), "by_source", dict(by_src))


if __name__ == "__main__":
    asyncio.run(main())
