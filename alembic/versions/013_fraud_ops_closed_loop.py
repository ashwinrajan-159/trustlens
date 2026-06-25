"""fraud-ops closed loop: investigations, reviews, knowledge base, weight governance (Phase 12)

Revision ID: 013_fraud_ops
Revises: 012_widen_encrypted
Create Date: 2026-06-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013_fraud_ops"
down_revision: Union[str, None] = "012_widen_encrypted"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TS = dict(server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    # Widen application status to fit UNDER_INVESTIGATION (19 chars).
    op.alter_column("applications", "status", existing_type=sa.String(16), type_=sa.String(24))

    # Alert investigation-assignment fields.
    op.add_column("fraud_alerts", sa.Column("claimed_by", sa.String(36), nullable=True))
    op.add_column("fraud_alerts", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("fraud_alerts", sa.Column("case_id", sa.String(36), sa.ForeignKey("investigation_cases.id"), nullable=True))
    op.create_index("ix_fraud_alerts_claimed_by", "fraud_alerts", ["claimed_by"])

    op.create_table(
        "investigation_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("alert_id", sa.String(36), sa.ForeignKey("fraud_alerts.id"), nullable=False),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("investigation_cases.id"), nullable=True),
        sa.Column("underwriter_id", sa.String(36), nullable=False),
        sa.Column("investigation_summary", sa.Text(), nullable=False),
        sa.Column("findings", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("recommendation", sa.String(32), nullable=False),
    )
    op.create_index("ix_investigation_reports_alert_id", "investigation_reports", ["alert_id"])
    op.create_index("ix_investigation_reports_underwriter_id", "investigation_reports", ["underwriter_id"])
    op.create_index("ix_investigation_reports_id", "investigation_reports", ["id"])

    op.create_table(
        "review_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("report_id", sa.String(36), sa.ForeignKey("investigation_reports.id"), nullable=False),
        sa.Column("alert_id", sa.String(36), sa.ForeignKey("fraud_alerts.id"), nullable=False),
        sa.Column("reviewer_id", sa.String(36), nullable=False),
        sa.Column("decision", sa.String(24), nullable=False),
        sa.Column("comments", sa.Text(), nullable=False, server_default=""),
        sa.Column("fp_reason_code", sa.String(32), nullable=True),
    )
    for col in ("report_id", "alert_id", "reviewer_id", "decision", "id"):
        op.create_index(f"ix_review_decisions_{col}", "review_decisions", [col])

    op.create_table(
        "false_positive_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("alert_id", sa.String(36), sa.ForeignKey("fraud_alerts.id"), nullable=False),
        sa.Column("review_decision_id", sa.String(36), sa.ForeignKey("review_decisions.id"), nullable=False),
        sa.Column("application_id", sa.String(36), nullable=False),
        sa.Column("signal_names", sa.JSON(), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("analyst_explanation", sa.Text(), nullable=False, server_default=""),
        sa.Column("fp_reason_code", sa.String(32), nullable=False),
        sa.Column("final_outcome", sa.String(32), nullable=True),
    )
    op.create_index("ix_false_positive_records_alert_id", "false_positive_records", ["alert_id"])
    op.create_index("ix_false_positive_records_application_id", "false_positive_records", ["application_id"])
    op.create_index("ix_false_positive_records_id", "false_positive_records", ["id"])

    op.create_table(
        "fraud_patterns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("category", sa.String(48), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("severity", sa.String(16), nullable=False, server_default="MEDIUM"),
        sa.Column("detection_logic", sa.JSON(), nullable=False),
        sa.Column("occurrences", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confirmed_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("false_positive_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pattern_confidence", sa.Float(), nullable=False, server_default="0"),
    )
    op.create_index("ix_fraud_patterns_name", "fraud_patterns", ["name"])
    op.create_index("ix_fraud_patterns_category", "fraud_patterns", ["category"])
    op.create_index("ix_fraud_patterns_id", "fraud_patterns", ["id"])

    op.create_table(
        "pattern_case_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("pattern_id", sa.String(36), sa.ForeignKey("fraud_patterns.id"), nullable=False),
        sa.Column("alert_id", sa.String(36), nullable=False),
        sa.Column("application_id", sa.String(36), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("signal_names", sa.JSON(), nullable=True),
        sa.UniqueConstraint("pattern_id", "alert_id", name="uq_pattern_alert"),
    )
    op.create_index("ix_pattern_case_links_pattern_id", "pattern_case_links", ["pattern_id"])
    op.create_index("ix_pattern_case_links_alert_id", "pattern_case_links", ["alert_id"])
    op.create_index("ix_pattern_case_links_id", "pattern_case_links", ["id"])

    op.create_table(
        "signal_performance",
        sa.Column("signal_name", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("times_triggered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confirmed_fraud_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("false_positive_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("precision_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("sample_sufficient", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("precision_ci_low", sa.Float(), nullable=False, server_default="0"),
        sa.Column("precision_ci_high", sa.Float(), nullable=False, server_default="1"),
        sa.Column("last_updated", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "signal_weight_config",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("weights", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="DRAFT"),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("approved_by", sa.String(36), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("version", name="uq_weight_config_version"),
    )
    op.create_index("ix_signal_weight_config_status", "signal_weight_config", ["status"])
    op.create_index("ix_signal_weight_config_id", "signal_weight_config", ["id"])

    # Reproducibility: which governed weight set produced each risk score.
    op.add_column("risk_assessments", sa.Column("weight_config_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("risk_assessments", "weight_config_version")
    op.drop_table("signal_weight_config")
    op.drop_table("signal_performance")
    op.drop_table("pattern_case_links")
    op.drop_table("fraud_patterns")
    op.drop_table("false_positive_records")
    op.drop_table("review_decisions")
    op.drop_table("investigation_reports")
    op.drop_index("ix_fraud_alerts_claimed_by", table_name="fraud_alerts")
    op.drop_column("fraud_alerts", "case_id")
    op.drop_column("fraud_alerts", "claimed_at")
    op.drop_column("fraud_alerts", "claimed_by")
    op.alter_column("applications", "status", existing_type=sa.String(24), type_=sa.String(16))
