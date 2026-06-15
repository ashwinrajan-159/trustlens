"""graph_analyses (Phase 7 — graph intelligence)

Revision ID: 008_graph_analyses
Revises: 007_property_business
Create Date: 2026-06-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008_graph_analyses"
down_revision: Union[str, None] = "007_property_business"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "graph_analyses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("graph_risk_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("fraud_connections_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("shared_pan_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("shared_account_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("shared_property_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ring_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("in_fraud_ring", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("connected_application_ids", sa.JSON(), nullable=True),
    )
    op.create_index("ix_graph_analyses_application_id", "graph_analyses", ["application_id"])
    op.create_index("ix_graph_analyses_id", "graph_analyses", ["id"])


def downgrade() -> None:
    op.drop_table("graph_analyses")
