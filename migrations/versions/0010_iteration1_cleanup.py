"""0010 迭代1：SessionMemory 唯一约束 + 删除冗余持久化表

Revision ID: 0010_iteration1_cleanup
Revises: 0009_controlled_memory

内容：
(a) session_memories 增加 (user_id, session_id) 唯一约束（S4 并发修复）。
    升级前防御性清理潜在重复行（保留最新 id 的一行）；正常部署中保存逻辑
    本就是 read-then-insert 单写路径，重复行只可能由并发竞态产生。
(b) drop agent_checkpoints / agent_task_steps / agent_tool_calls 三张冗余表：
    - 检查点改由 LangGraph PostgresCheckpointSaver（lg_* 表）负责；
    - task_steps / tool_calls 从未有任何写入方，纯死代码。
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_iteration1_cleanup"
down_revision: Union[str, None] = "0009_controlled_memory"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # (a) 防御性去重：每组 (user_id, session_id) 只保留 id 最大的一行
    op.execute(
        """
        DELETE FROM session_memories a
        USING session_memories b
        WHERE a.user_id = b.user_id
          AND a.session_id = b.session_id
          AND a.id < b.id
        """
    )
    op.create_unique_constraint(
        "uq_session_memories_user_session",
        "session_memories",
        ["user_id", "session_id"],
    )

    # (b) 删除冗余持久化表
    op.drop_index("ix_agent_checkpoints_task_id", table_name="agent_checkpoints")
    op.drop_table("agent_checkpoints")
    op.drop_index("ix_agent_tool_calls_task_id", table_name="agent_tool_calls")
    op.drop_table("agent_tool_calls")
    op.drop_index("ix_agent_task_steps_task_id", table_name="agent_task_steps")
    op.drop_table("agent_task_steps")


def downgrade() -> None:
    op.create_table(
        "agent_task_steps",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("step_name", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["agent_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_task_steps_task_id", "agent_task_steps", ["task_id"])

    op.create_table(
        "agent_tool_calls",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=True),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["agent_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_tool_calls_task_id", "agent_tool_calls", ["task_id"])

    op.create_table(
        "agent_checkpoints",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("node_name", sa.String(length=64), nullable=False),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["agent_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_checkpoints_task_id", "agent_checkpoints", ["task_id"])

    op.drop_constraint(
        "uq_session_memories_user_session", "session_memories", type_="unique"
    )
