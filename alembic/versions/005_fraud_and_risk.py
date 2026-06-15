"""fraud_signals + risk_assessments (Phase 3b)

Revision ID: 005_fraud_and_risk
Revises: 004_extracted_entities
Create Date: 2026-06-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_fraud_and_risk"
down_revision: Union[str, None] = "004_extracted_entities"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fraud_signals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id"), nullable=True),
        sa.Column("signal_type", sa.String(48), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("signal_scope", sa.String(16), nullable=False, server_default="DOCUMENT"),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("rule_name", sa.String(128), nullable=False),
        sa.Column("engine_version", sa.String(32), nullable=False, server_default="1.0.0"),
        sa.Column("source_document_ids", sa.JSON(), nullable=True),
        sa.Column("is_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_fraud_signals_application_id", "fraud_signals", ["application_id"])
    op.create_index("ix_fraud_signals_document_id", "fraud_signals", ["document_id"])
    op.create_index("ix_fraud_signals_severity", "fraud_signals", ["severity"])
    op.create_index("ix_fraud_signals_id", "fraud_signals", ["id"])

    op.create_table(
        "risk_assessments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("total_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("risk_tier", sa.String(16), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=True),
        sa.Column("by_category", sa.JSON(), nullable=True),
        sa.Column("engine_version", sa.String(32), nullable=False, server_default="1.0.0"),
    )
    op.create_index("ix_risk_assessments_application_id", "risk_assessments", ["application_id"])
    op.create_index("ix_risk_assessments_id", "risk_assessments", ["id"])


def downgrade() -> None:
    op.drop_table("risk_assessments")
    op.drop_table("fraud_signals")
