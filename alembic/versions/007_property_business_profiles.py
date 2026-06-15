"""property_profiles + business_profiles (Phase 6)

Revision ID: 007_property_business
Revises: 006_identity_profiles
Create Date: 2026-06-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007_property_business"
down_revision: Union[str, None] = "006_identity_profiles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "property_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("survey_numbers", sa.JSON(), nullable=True),
        sa.Column("area", sa.Float(), nullable=True),
        sa.Column("sale_consideration", sa.Float(), nullable=True),
        sa.Column("valuation", sa.Float(), nullable=True),
        sa.Column("valuation_ratio", sa.Float(), nullable=True),
        sa.Column("is_inflated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("duplicate_collateral_app_ids", sa.JSON(), nullable=True),
    )
    op.create_index("ix_property_profiles_application_id", "property_profiles", ["application_id"])
    op.create_index("ix_property_profiles_id", "property_profiles", ["id"])

    op.create_table(
        "business_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("itr_revenue", sa.Float(), nullable=True),
        sa.Column("gst_revenue", sa.Float(), nullable=True),
        sa.Column("net_profit", sa.Float(), nullable=True),
        sa.Column("revenue_gap_ratio", sa.Float(), nullable=True),
    )
    op.create_index("ix_business_profiles_application_id", "business_profiles", ["application_id"])
    op.create_index("ix_business_profiles_id", "business_profiles", ["id"])


def downgrade() -> None:
    op.drop_table("business_profiles")
    op.drop_table("property_profiles")
