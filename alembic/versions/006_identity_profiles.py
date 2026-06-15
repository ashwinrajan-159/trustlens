"""identity_profiles (Phase 4 — identity intelligence)

Revision ID: 006_identity_profiles
Revises: 005_fraud_and_risk
Create Date: 2026-06-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006_identity_profiles"
down_revision: Union[str, None] = "005_fraud_and_risk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "identity_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("resolved_name", sa.String(512), nullable=True),       # ciphertext
        sa.Column("resolved_name_masked", sa.String(128), nullable=True),
        sa.Column("pan", sa.String(64), nullable=True),                  # ciphertext
        sa.Column("pan_masked", sa.String(32), nullable=True),
        sa.Column("aadhaar_masked", sa.String(32), nullable=True),
        sa.Column("dob", sa.String(32), nullable=True),                  # ciphertext
        sa.Column("distinct_name_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("distinct_pan_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("distinct_dob_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("synthetic_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("is_synthetic_suspected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("indicators", sa.JSON(), nullable=True),
    )
    op.create_index("ix_identity_profiles_application_id", "identity_profiles", ["application_id"])
    op.create_index("ix_identity_profiles_id", "identity_profiles", ["id"])


def downgrade() -> None:
    op.drop_table("identity_profiles")
