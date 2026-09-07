"""食物成分库。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class FoodItem(Base):
    """食物条目：每 100g 宏量（确定性计算基础）。

    source=manual 为本地/用户录入；source=usda-foundation 来自 USDA FDC（优先中文名）。
    """

    __tablename__ = "food_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(64), default="manual", index=True)
    external_id: Mapped[str | None] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(256), unique=True, index=True, nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(256), index=True)
    brand: Mapped[str | None] = mapped_column(String(128))
    category: Mapped[str | None] = mapped_column(String(64))
    serving_g: Mapped[float] = mapped_column(Float, default=100.0)
    kcal_per_100g: Mapped[float] = mapped_column(Float, nullable=False)
    protein_g_per_100g: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    carb_g_per_100g: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fat_g_per_100g: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
