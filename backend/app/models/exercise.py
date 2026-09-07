"""动作库（参考 workout.cool + exercises-dataset）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Exercise(Base):
    """标准化动作目录：供计划生成、打卡关联与 RAG 引用。

    设计取自 workout.cool 的「可筛选动作库」理念；
    字段对齐 exercises-dataset（文本入库，媒体默认不拷贝）。
    """

    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(64), default="exercises-dataset", index=True)
    external_id: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    name_en: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    name_zh: Mapped[str | None] = mapped_column(String(256), index=True)
    body_part: Mapped[str | None] = mapped_column(String(64), index=True)
    equipment: Mapped[str | None] = mapped_column(String(64), index=True)
    primary_muscle: Mapped[str | None] = mapped_column(String(64), index=True)
    muscle_group: Mapped[str | None] = mapped_column(String(64))
    secondary_muscles: Mapped[list] = mapped_column(JSONB, default=list)
    instructions_zh: Mapped[str | None] = mapped_column(Text)
    instructions_en: Mapped[str | None] = mapped_column(Text)
    steps_zh: Mapped[list] = mapped_column(JSONB, default=list)
    steps_en: Mapped[list] = mapped_column(JSONB, default=list)
    # 仅保留出处说明；不默认入库受版权限制的 GIF/图片文件
    media_note: Mapped[str | None] = mapped_column(String(512))
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
