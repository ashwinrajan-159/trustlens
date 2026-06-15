"""ocr_results table (Phase 2)

Revision ID: 003_ocr_results
Revises: 002_hardening
Create Date: 2026-06-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003_ocr_results"
down_revision: Union[str, None] = "002_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ocr_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pages_data", sa.JSON(), nullable=True),
        sa.Column("engine", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False, server_default="unknown"),
    )
    op.create_index("ix_ocr_results_document_id", "ocr_results", ["document_id"])
    op.create_index("ix_ocr_results_id", "ocr_results", ["id"])


def downgrade() -> None:
    op.drop_table("ocr_results")
