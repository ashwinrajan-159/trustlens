"""fraud_alerts + investigation_cases (Phase 10)

Revision ID: 011_alerts_cases
Revises: 010_ml_platform
Create Date: 2026-06-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011_alerts_cases"
down_revision: Union[str, None] = "010_ml_platform"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TS = dict(server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "fraud_alerts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("alert_number", sa.String(32), nullable=False),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("alert_type", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="OPEN"),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("rbi_reporting_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rbi_report_type", sa.String(16), nullable=False, server_default="NONE"),
        sa.Column("rbi_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sla_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sla_breached", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(36), nullable=True),
    )
    op.create_index("ix_fraud_alerts_alert_number", "fraud_alerts", ["alert_number"], unique=True)
    op.create_index("ix_fraud_alerts_application_id", "fraud_alerts", ["application_id"])
    op.create_index("ix_fraud_alerts_severity", "fraud_alerts", ["severity"])
    op.create_index("ix_fraud_alerts_status", "fraud_alerts", ["status"])
    op.create_index("ix_fraud_alerts_id", "fraud_alerts", ["id"])

    op.create_table(
        "investigation_cases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("case_number", sa.String(32), nullable=False),
        sa.Column("case_type", sa.String(24), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="OPEN"),
        sa.Column("priority", sa.String(16), nullable=False, server_default="MEDIUM"),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("application_ids", sa.JSON(), nullable=True),
        sa.Column("alert_ids", sa.JSON(), nullable=True),
        sa.Column("assigned_to", sa.String(36), nullable=True),
        sa.Column("sla_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", sa.String(36), nullable=True),
        sa.Column("closed_outcome", sa.String(64), nullable=True),
    )
    op.create_index("ix_investigation_cases_case_number", "investigation_cases", ["case_number"], unique=True)
    op.create_index("ix_investigation_cases_status", "investigation_cases", ["status"])
    op.create_index("ix_investigation_cases_id", "investigation_cases", ["id"])


def downgrade() -> None:
    op.drop_table("investigation_cases")
    op.drop_table("fraud_alerts")
