"""0011 迭代2：可靠性索引（reaper / TTL 清理 / 并发上限支撑）

Revision ID: 0011_iteration2_reliability
Revises: 0010_iteration1_cleanup

内容：
(a) agent_tasks(user_id, status) 复合索引：每用户并发任务上限计数。
(b) agent_tasks(status, updated_at) 复合索引：stale reaper 扫描。
(c) agent_task_events(created_at) 索引：事件 TTL 清理。
    注：(task_id, seq) 唯一约束自 0004 已存在，此处不重复创建；
    写入侧的冲突重试在应用层（append_task_event）完成。
(d) lg_checkpoints(created_at) 索引：检查点 TTL 清理。
(e) user_memories(confirmed, created_at) 复合索引：未确认提议 TTL 清理。
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0011_iteration2_reliability"
down_revision: Union[str, None] = "0010_iteration1_cleanup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # (a) 每用户并发任务上限计数
    op.create_index(
        "ix_agent_tasks_user_status",
        "agent_tasks",
        ["user_id", "status"],
    )
    # (b) stale reaper 扫描（queued/running + updated_at）
    op.create_index(
        "ix_agent_tasks_status_updated",
        "agent_tasks",
        ["status", "updated_at"],
    )
    # (c) 任务事件 TTL 清理
    op.create_index(
        "ix_agent_task_events_created_at",
        "agent_task_events",
        ["created_at"],
    )
    # (d) LangGraph 检查点 TTL 清理
    op.create_index(
        "ix_lg_checkpoints_created_at",
        "lg_checkpoints",
        ["created_at"],
    )
    # (e) 未确认记忆提议 TTL 清理
    op.create_index(
        "ix_user_memories_confirmed_created",
        "user_memories",
        ["confirmed", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_memories_confirmed_created", table_name="user_memories")
    op.drop_index("ix_lg_checkpoints_created_at", table_name="lg_checkpoints")
    op.drop_index("ix_agent_task_events_created_at", table_name="agent_task_events")
    op.drop_index("ix_agent_tasks_status_updated", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_user_status", table_name="agent_tasks")
