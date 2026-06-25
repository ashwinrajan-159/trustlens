"""document fingerprints — perceptual-hash store for cross-application reuse detection (forensics)

Revision ID: 014_doc_fingerprints
Revises: 013_fraud_ops
Create Date: 2026-06-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014_doc_fingerprints"
down_revision: Union[str, None] = "013_fraud_ops"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TS = dict(server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "document_fingerprints",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("phash_hex", sa.String(128), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("extra", sa.JSON(), nullable=True),
    )
    op.create_index("ix_document_fingerprints_document_id", "document_fingerprints", ["document_id"])
    op.create_index("ix_document_fingerprints_application_id", "document_fingerprints", ["application_id"])
    op.create_index("ix_document_fingerprints_phash_hex", "document_fingerprints", ["phash_hex"])


def downgrade() -> None:
    op.drop_index("ix_document_fingerprints_phash_hex", table_name="document_fingerprints")
    op.drop_index("ix_document_fingerprints_application_id", table_name="document_fingerprints")
    op.drop_index("ix_document_fingerprints_document_id", table_name="document_fingerprints")
    op.drop_table("document_fingerprints")
