"""food_items: source + external_id for USDA Foundation Foods

Revision ID: 0003_foods_source
Revises: 0002_exercises
Create Date: 2026-07-14
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_foods_source"
down_revision: Union[str, None] = "0002_exercises"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "food_items",
        sa.Column("source", sa.String(length=64), nullable=False, server_default="manual"),
    )
    op.add_column(
        "food_items",
        sa.Column("external_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "food_items",
        sa.Column("name_en", sa.String(length=256), nullable=True),
    )
    op.alter_column(
        "food_items",
        "name",
        existing_type=sa.String(length=128),
        type_=sa.String(length=256),
        existing_nullable=False,
    )
    op.create_index("ix_food_items_source", "food_items", ["source"])
    op.create_index("ix_food_items_external_id", "food_items", ["external_id"])
    op.create_index("ix_food_items_name_en", "food_items", ["name_en"])
    op.create_index(
        "uq_food_items_source_external_id",
        "food_items",
        ["source", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_food_items_source_external_id", table_name="food_items")
    op.drop_index("ix_food_items_name_en", table_name="food_items")
    op.drop_index("ix_food_items_external_id", table_name="food_items")
    op.drop_index("ix_food_items_source", table_name="food_items")
    op.alter_column(
        "food_items",
        "name",
        existing_type=sa.String(length=256),
        type_=sa.String(length=128),
        existing_nullable=False,
    )
    op.drop_column("food_items", "name_en")
    op.drop_column("food_items", "external_id")
    op.drop_column("food_items", "source")
