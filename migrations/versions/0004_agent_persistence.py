"""Agent 任务事件/步骤/工具调用/检查点持久化

Revision ID: 0004_agent_persistence
Revises: 0003_foods_source
Create Date: 2026-07-15
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_agent_persistence"
down_revision: Union[str, None] = "0003_foods_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent_tasks", sa.Column("intent", sa.String(length=64), nullable=True))
    op.add_column("agent_tasks", sa.Column("trace_id", sa.String(length=64), nullable=True))
    op.add_column("agent_tasks", sa.Column("error_code", sa.String(length=64), nullable=True))
    op.add_column("agent_tasks", sa.Column("current_step", sa.String(length=64), nullable=True))
    op.add_column("agent_tasks", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agent_tasks", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "agent_task_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["agent_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "seq", name="uq_agent_task_events_task_seq"),
    )
    op.create_index("ix_agent_task_events_task_id", "agent_task_events", ["task_id"])

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


def downgrade() -> None:
    op.drop_index("ix_agent_checkpoints_task_id", table_name="agent_checkpoints")
    op.drop_table("agent_checkpoints")
    op.drop_index("ix_agent_tool_calls_task_id", table_name="agent_tool_calls")
    op.drop_table("agent_tool_calls")
    op.drop_index("ix_agent_task_steps_task_id", table_name="agent_task_steps")
    op.drop_table("agent_task_steps")
    op.drop_index("ix_agent_task_events_task_id", table_name="agent_task_events")
    op.drop_table("agent_task_events")
    op.drop_column("agent_tasks", "completed_at")
    op.drop_column("agent_tasks", "started_at")
    op.drop_column("agent_tasks", "current_step")
    op.drop_column("agent_tasks", "error_code")
    op.drop_column("agent_tasks", "trace_id")
    op.drop_column("agent_tasks", "intent")
