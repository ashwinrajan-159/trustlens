"""event_log outbox (Phase 8 — events & streaming)

Revision ID: 009_event_log
Revises: 008_graph_analyses
Create Date: 2026-06-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009_event_log"
down_revision: Union[str, None] = "008_graph_analyses"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("topic", sa.String(128), nullable=False),
        sa.Column("aggregate_type", sa.String(48), nullable=False),
        sa.Column("aggregate_id", sa.String(36), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_event_log_event_id", "event_log", ["event_id"], unique=True)
    op.create_index("ix_event_log_event_type", "event_log", ["event_type"])
    op.create_index("ix_event_log_aggregate_id", "event_log", ["aggregate_id"])
    op.create_index("ix_event_log_correlation_id", "event_log", ["correlation_id"])
    op.create_index("ix_event_log_status", "event_log", ["status"])
    op.create_index("ix_event_log_id", "event_log", ["id"])


def downgrade() -> None:
    op.drop_table("event_log")
