"""extracted_entities table (Phase 3 — extraction)

Revision ID: 004_extracted_entities
Revises: 003_ocr_results
Create Date: 2026-06-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_extracted_entities"
down_revision: Union[str, None] = "003_ocr_results"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "extracted_entities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("value", sa.String(1024), nullable=True),       # ciphertext for sensitive
        sa.Column("masked_value", sa.String(256), nullable=True),
        sa.Column("is_sensitive", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("extraction_method", sa.String(16), nullable=False, server_default="REGEX"),
        sa.Column("source_page", sa.Integer(), nullable=True),
    )
    op.create_index("ix_extracted_entities_document_id", "extracted_entities", ["document_id"])
    op.create_index("ix_extracted_entities_application_id", "extracted_entities", ["application_id"])
    op.create_index("ix_extracted_entities_id", "extracted_entities", ["id"])


def downgrade() -> None:
    op.drop_table("extracted_entities")
