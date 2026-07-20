"""exercises catalog + workout_log.exercise_id

Revision ID: 0002_exercises
Revises: 0001_initial
Create Date: 2026-07-14
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_exercises"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "exercises",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False, server_default="exercises-dataset"),
        sa.Column("external_id", sa.String(length=32), nullable=False),
        sa.Column("name_en", sa.String(length=256), nullable=False),
        sa.Column("name_zh", sa.String(length=256), nullable=True),
        sa.Column("body_part", sa.String(length=64), nullable=True),
        sa.Column("equipment", sa.String(length=64), nullable=True),
        sa.Column("primary_muscle", sa.String(length=64), nullable=True),
        sa.Column("muscle_group", sa.String(length=64), nullable=True),
        sa.Column("secondary_muscles", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("instructions_zh", sa.Text(), nullable=True),
        sa.Column("instructions_en", sa.Text(), nullable=True),
        sa.Column("steps_zh", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("steps_en", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("media_note", sa.String(length=512), nullable=True),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id"),
    )
    op.create_index("ix_exercises_source", "exercises", ["source"])
    op.create_index("ix_exercises_external_id", "exercises", ["external_id"])
    op.create_index("ix_exercises_name_en", "exercises", ["name_en"])
    op.create_index("ix_exercises_name_zh", "exercises", ["name_zh"])
    op.create_index("ix_exercises_body_part", "exercises", ["body_part"])
    op.create_index("ix_exercises_equipment", "exercises", ["equipment"])
    op.create_index("ix_exercises_primary_muscle", "exercises", ["primary_muscle"])

    op.add_column(
        "workout_logs",
        sa.Column("exercise_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_workout_logs_exercise_id",
        "workout_logs",
        "exercises",
        ["exercise_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_workout_logs_exercise_id", "workout_logs", ["exercise_id"])


def downgrade() -> None:
    op.drop_index("ix_workout_logs_exercise_id", table_name="workout_logs")
    op.drop_constraint("fk_workout_logs_exercise_id", "workout_logs", type_="foreignkey")
    op.drop_column("workout_logs", "exercise_id")

    op.drop_index("ix_exercises_primary_muscle", table_name="exercises")
    op.drop_index("ix_exercises_equipment", table_name="exercises")
    op.drop_index("ix_exercises_body_part", table_name="exercises")
    op.drop_index("ix_exercises_name_zh", table_name="exercises")
    op.drop_index("ix_exercises_name_en", table_name="exercises")
    op.drop_index("ix_exercises_external_id", table_name="exercises")
    op.drop_index("ix_exercises_source", table_name="exercises")
    op.drop_table("exercises")
