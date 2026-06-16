"""ML platform tables (Phase 9)

Revision ID: 010_ml_platform
Revises: 009_event_log
Create Date: 2026-06-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010_ml_platform"
down_revision: Union[str, None] = "009_event_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TS = dict(server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "ml_feature_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("feature_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_ml_feature_snapshots_application_id", "ml_feature_snapshots", ["application_id"])
    op.create_index("ix_ml_feature_snapshots_id", "ml_feature_snapshots", ["id"])

    op.create_table(
        "ml_labels",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("label", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=True),
    )
    op.create_index("ix_ml_labels_application_id", "ml_labels", ["application_id"])
    op.create_index("ix_ml_labels_id", "ml_labels", ["id"])

    op.create_table(
        "ml_models",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("algorithm", sa.String(48), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="TRAINED"),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("feature_names", sa.JSON(), nullable=True),
        sa.Column("artifact_path", sa.String(512), nullable=True),
        sa.Column("training_samples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_champion", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approved_by", sa.String(36), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_ml_models_name", "ml_models", ["name"])
    op.create_index("ix_ml_models_status", "ml_models", ["status"])
    op.create_index("ix_ml_models_is_champion", "ml_models", ["is_champion"])
    op.create_index("ix_ml_models_id", "ml_models", ["id"])

    op.create_table(
        "ml_predictions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("model_id", sa.String(36), sa.ForeignKey("ml_models.id"), nullable=False),
        sa.Column("fraud_probability", sa.Float(), nullable=False),
        sa.Column("risk_tier", sa.String(16), nullable=False),
        sa.Column("shap_top", sa.JSON(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=False, server_default="0"),
    )
    op.create_index("ix_ml_predictions_application_id", "ml_predictions", ["application_id"])
    op.create_index("ix_ml_predictions_id", "ml_predictions", ["id"])


def downgrade() -> None:
    op.drop_table("ml_predictions")
    op.drop_table("ml_models")
    op.drop_table("ml_labels")
    op.drop_table("ml_feature_snapshots")
