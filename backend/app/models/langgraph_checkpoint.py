"""LangGraph 全状态检查点表（与手工 agent_checkpoints 快照分离）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, LargeBinary, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class LGCheckpoint(Base):
    __tablename__ = "lg_checkpoints"
    __table_args__ = (
        UniqueConstraint("thread_id", "checkpoint_ns", "checkpoint_id", name="uq_lg_ckpt"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    checkpoint_ns: Mapped[str] = mapped_column(String(64), default="", server_default="")
    checkpoint_id: Mapped[str] = mapped_column(String(128))
    parent_checkpoint_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    checkpoint_type: Mapped[str] = mapped_column(String(64))
    checkpoint_data: Mapped[bytes] = mapped_column(LargeBinary)
    metadata_type: Mapped[str] = mapped_column(String(64))
    metadata_data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LGChannelBlob(Base):
    __tablename__ = "lg_channel_blobs"
    __table_args__ = (
        UniqueConstraint(
            "thread_id", "checkpoint_ns", "channel", "version", name="uq_lg_channel_blob"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    checkpoint_ns: Mapped[str] = mapped_column(String(64), default="", server_default="")
    channel: Mapped[str] = mapped_column(String(128))
    version: Mapped[str] = mapped_column(String(64))
    blob_type: Mapped[str] = mapped_column(String(64))
    blob_data: Mapped[bytes] = mapped_column(LargeBinary)


class LGCheckpointWrite(Base):
    __tablename__ = "lg_checkpoint_writes"
    __table_args__ = (
        UniqueConstraint(
            "thread_id",
            "checkpoint_ns",
            "checkpoint_id",
            "task_id",
            "write_idx",
            name="uq_lg_ckpt_write",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    checkpoint_ns: Mapped[str] = mapped_column(String(64), default="", server_default="")
    checkpoint_id: Mapped[str] = mapped_column(String(128), index=True)
    task_id: Mapped[str] = mapped_column(String(128))
    write_idx: Mapped[int] = mapped_column()
    channel: Mapped[str] = mapped_column(String(128))
    blob_type: Mapped[str] = mapped_column(String(64))
    blob_data: Mapped[bytes] = mapped_column(LargeBinary)
    task_path: Mapped[str] = mapped_column(String(256), default="", server_default="")
