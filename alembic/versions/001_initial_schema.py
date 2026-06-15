"""initial schema: users, applications, documents, audit_logs (WORM)

Revision ID: 001_initial
Revises:
Create Date: 2026-06-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Enums persist as VARCHAR (native_enum=False in the models) for portability.


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("data_consent_given_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_id", "users", ["id"])

    op.create_table(
        "applications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("application_number", sa.String(32), nullable=False),
        sa.Column("applicant_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("loan_type", sa.String(16), nullable=False),
        sa.Column("loan_amount_requested", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("risk_tier", sa.String(16), nullable=True),
        sa.Column("current_risk_score", sa.Float(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
    )
    op.create_index("ix_applications_number", "applications", ["application_number"], unique=True)
    op.create_index("ix_applications_applicant_id", "applications", ["applicant_id"])
    op.create_index("ix_applications_status", "applications", ["status"])
    op.create_index("ix_applications_id", "applications", ["id"])

    op.create_table(
        "documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("document_type", sa.String(32), nullable=False),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("storage_bucket", sa.String(128), nullable=False),
        sa.Column("storage_key", sa.String(1024), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_current_version", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("uploaded_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
    )
    op.create_index("ix_documents_application_id", "documents", ["application_id"])
    op.create_index("ix_documents_checksum", "documents", ["checksum_sha256"])
    op.create_index("ix_documents_status", "documents", ["status"])
    op.create_index("ix_documents_id", "documents", ["id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=True),
        sa.Column("before_state", sa.JSON(), nullable=True),
        sa.Column("after_state", sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=True),
    )
    op.create_index("ix_audit_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_entity_type", "audit_logs", ["entity_type"])
    op.create_index("ix_audit_entity_id", "audit_logs", ["entity_id"])
    op.create_index("ix_audit_correlation_id", "audit_logs", ["correlation_id"])
    op.create_index("ix_audit_logs_id", "audit_logs", ["id"])

    # ── WORM enforcement (PostgreSQL only): turn UPDATE/DELETE into no-ops. ──
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE RULE audit_logs_no_update AS ON UPDATE TO audit_logs DO INSTEAD NOTHING")
        op.execute("CREATE RULE audit_logs_no_delete AS ON DELETE TO audit_logs DO INSTEAD NOTHING")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP RULE IF EXISTS audit_logs_no_update ON audit_logs")
        op.execute("DROP RULE IF EXISTS audit_logs_no_delete ON audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("documents")
    op.drop_table("applications")
    op.drop_table("users")
