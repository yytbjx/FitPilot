"""0012 分层对话记忆（活跃/摘要/原始）

Revision ID: 0012_conversation_memory
Revises: 0011_iteration2_reliability

说明：
- 原始层：完整消息内容
- 摘要层：summary + embedding（JSON 向量，会话内余弦召回；不强制 pgvector 扩展）
- 活跃层：应用侧按 turn_index 取最近 K 轮
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_conversation_memory"
down_revision: Union[str, None] = "0011_iteration2_reliability"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversation_memory",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("message_id", sa.String(length=64), nullable=False),
        sa.Column("turn_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("embedding", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("importance", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "message_id", name="uq_conversation_memory_session_msg"),
    )
    op.create_index("ix_conversation_memory_user_id", "conversation_memory", ["user_id"])
    op.create_index(
        "ix_conversation_memory_session_created",
        "conversation_memory",
        ["session_id", "created_at"],
    )
    op.create_index(
        "ix_conversation_memory_session_turn",
        "conversation_memory",
        ["session_id", "turn_index"],
    )
    op.create_index("ix_conversation_memory_task_id", "conversation_memory", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_conversation_memory_task_id", table_name="conversation_memory")
    op.drop_index("ix_conversation_memory_session_turn", table_name="conversation_memory")
    op.drop_index("ix_conversation_memory_session_created", table_name="conversation_memory")
    op.drop_index("ix_conversation_memory_user_id", table_name="conversation_memory")
    op.drop_table("conversation_memory")
