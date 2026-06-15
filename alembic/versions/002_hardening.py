"""hardening: audit hash-chain + WORM trigger, composite indexes, MFA + consent columns

Revision ID: 002_hardening
Revises: 001_initial
Create Date: 2026-06-12

Covers IMPROVEMENTS.md items #7 (tamper-evident audit), #12 (composite indexes),
#24 (consent withdrawal column) and #25 (MFA columns).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_hardening"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Audit hash chain (#7) ──
    op.add_column("audit_logs", sa.Column("prev_hash", sa.String(64), nullable=True))
    op.add_column("audit_logs", sa.Column("entry_hash", sa.String(64), nullable=True))

    # ── User MFA (#25) + consent withdrawal (#24) ──
    op.add_column("users", sa.Column("data_consent_withdrawn_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("users", sa.Column("mfa_secret", sa.String(255), nullable=True))

    # ── Composite / partial indexes (#12) ──
    if op.get_bind().dialect.name == "postgresql":
        op.create_index(
            "ix_documents_app_current",
            "documents",
            ["application_id"],
            unique=False,
            postgresql_where=sa.text("is_current_version AND deleted_at IS NULL"),
        )
        op.execute(
            "CREATE INDEX ix_applications_applicant_created "
            "ON applications (applicant_id, created_at DESC) WHERE deleted_at IS NULL"
        )

        # ── WORM: replace silent no-op rules with loud triggers (#7) ──
        op.execute("DROP RULE IF EXISTS audit_logs_no_update ON audit_logs")
        op.execute("DROP RULE IF EXISTS audit_logs_no_delete ON audit_logs")
        op.execute(
            """
            CREATE OR REPLACE FUNCTION audit_logs_immutable() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'audit_logs is append-only (WORM); % blocked', TG_OP;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            "CREATE TRIGGER audit_logs_no_modify BEFORE UPDATE OR DELETE ON audit_logs "
            "FOR EACH ROW EXECUTE FUNCTION audit_logs_immutable()"
        )
    else:
        op.create_index(
            "ix_documents_app_current", "documents", ["application_id", "is_current_version"]
        )
        op.create_index(
            "ix_applications_applicant_created", "applications", ["applicant_id", "created_at"]
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_logs_no_modify ON audit_logs")
        op.execute("DROP FUNCTION IF EXISTS audit_logs_immutable()")
        op.execute("CREATE RULE audit_logs_no_update AS ON UPDATE TO audit_logs DO INSTEAD NOTHING")
        op.execute("CREATE RULE audit_logs_no_delete AS ON DELETE TO audit_logs DO INSTEAD NOTHING")

    op.drop_index("ix_applications_applicant_created", table_name="applications")
    op.drop_index("ix_documents_app_current", table_name="documents")
    op.drop_column("users", "mfa_secret")
    op.drop_column("users", "mfa_enabled")
    op.drop_column("users", "data_consent_withdrawn_at")
    op.drop_column("audit_logs", "entry_hash")
    op.drop_column("audit_logs", "prev_hash")
