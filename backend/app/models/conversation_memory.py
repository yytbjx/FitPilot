"""分层对话记忆 ORM：原始消息 + 摘要向量。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ConversationMemory(Base):
    """会话消息记忆（Archival 原文 + Recall 摘要/向量）。"""

    __tablename__ = "conversation_memory"
    __table_args__ = (
        UniqueConstraint("session_id", "message_id", name="uq_conversation_memory_session_msg"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    message_id: Mapped[str] = mapped_column(String(64), nullable=False)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list | None] = mapped_column(JSONB)
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    task_id: Mapped[str | None] = mapped_column(String(64), index=True)
    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
