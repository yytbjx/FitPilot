"""LangGraph 全状态检查点表

Revision ID: 0006_langgraph_checkpoint
Revises: 0005_engineering_p1
Create Date: 2026-07-15
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_langgraph_checkpoint"
down_revision: Union[str, None] = "0005_engineering_p1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lg_checkpoints",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("checkpoint_ns", sa.String(length=64), server_default="", nullable=False),
        sa.Column("checkpoint_id", sa.String(length=128), nullable=False),
        sa.Column("parent_checkpoint_id", sa.String(length=128), nullable=True),
        sa.Column("checkpoint_type", sa.String(length=64), nullable=False),
        sa.Column("checkpoint_data", sa.LargeBinary(), nullable=False),
        sa.Column("metadata_type", sa.String(length=64), nullable=False),
        sa.Column("metadata_data", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("thread_id", "checkpoint_ns", "checkpoint_id", name="uq_lg_ckpt"),
    )
    op.create_index("ix_lg_checkpoints_thread_id", "lg_checkpoints", ["thread_id"])

    op.create_table(
        "lg_channel_blobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("checkpoint_ns", sa.String(length=64), server_default="", nullable=False),
        sa.Column("channel", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("blob_type", sa.String(length=64), nullable=False),
        sa.Column("blob_data", sa.LargeBinary(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "thread_id", "checkpoint_ns", "channel", "version", name="uq_lg_channel_blob"
        ),
    )
    op.create_index("ix_lg_channel_blobs_thread_id", "lg_channel_blobs", ["thread_id"])

    op.create_table(
        "lg_checkpoint_writes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("checkpoint_ns", sa.String(length=64), server_default="", nullable=False),
        sa.Column("checkpoint_id", sa.String(length=128), nullable=False),
        sa.Column("task_id", sa.String(length=128), nullable=False),
        sa.Column("write_idx", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=128), nullable=False),
        sa.Column("blob_type", sa.String(length=64), nullable=False),
        sa.Column("blob_data", sa.LargeBinary(), nullable=False),
        sa.Column("task_path", sa.String(length=256), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "thread_id",
            "checkpoint_ns",
            "checkpoint_id",
            "task_id",
            "write_idx",
            name="uq_lg_ckpt_write",
        ),
    )
    op.create_index("ix_lg_checkpoint_writes_thread_id", "lg_checkpoint_writes", ["thread_id"])
    op.create_index("ix_lg_checkpoint_writes_checkpoint_id", "lg_checkpoint_writes", ["checkpoint_id"])


def downgrade() -> None:
    op.drop_index("ix_lg_checkpoint_writes_checkpoint_id", table_name="lg_checkpoint_writes")
    op.drop_index("ix_lg_checkpoint_writes_thread_id", table_name="lg_checkpoint_writes")
    op.drop_table("lg_checkpoint_writes")
    op.drop_index("ix_lg_channel_blobs_thread_id", table_name="lg_channel_blobs")
    op.drop_table("lg_channel_blobs")
    op.drop_index("ix_lg_checkpoints_thread_id", table_name="lg_checkpoints")
    op.drop_table("lg_checkpoints")
