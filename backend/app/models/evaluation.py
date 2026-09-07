"""评估运行持久化模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_name: Mapped[str] = mapped_column(String(128), default="full_eval")
    config_path: Mapped[str | None] = mapped_column(String(512))
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[str | None] = mapped_column(Text)
    report_json: Mapped[dict | None] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvaluationCase(Base):
    __tablename__ = "evaluation_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True)
    layer: Mapped[str] = mapped_column(String(32))
    case_id: Mapped[str | None] = mapped_column(String(64))
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    metrics: Mapped[dict | None] = mapped_column(JSON)
    detail: Mapped[dict | None] = mapped_column(JSON)


class EvaluationResult(Base):
    """层级别汇总结果。"""

    __tablename__ = "evaluation_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True)
    layer: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(128))
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[str | None] = mapped_column(Text)
    metrics: Mapped[dict | None] = mapped_column(JSON)
