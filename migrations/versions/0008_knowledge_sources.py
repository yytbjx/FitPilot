"""知识源清单表 knowledge_sources

Revision ID: 0008_knowledge_sources
Revises: 0007_evaluation_persistence
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_knowledge_sources"
down_revision: Union[str, None] = "0007_evaluation_persistence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledge_sources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("original_path", sa.String(length=1024), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("document_version", sa.String(length=64), nullable=True),
        sa.Column("parser_version", sa.String(length=32), nullable=True),
        sa.Column("chunker_version", sa.String(length=32), nullable=True),
        sa.Column("embedding_version", sa.String(length=128), nullable=True),
        sa.Column("authority_level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("effective_date", sa.String(length=32), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("ingestion_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id"),
    )
    op.create_index("ix_knowledge_sources_source_id", "knowledge_sources", ["source_id"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_sources_source_id", table_name="knowledge_sources")
    op.drop_table("knowledge_sources")
