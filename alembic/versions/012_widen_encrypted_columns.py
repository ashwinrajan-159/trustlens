"""widen identity_profiles encrypted columns to fit Fernet ciphertext

Revision ID: 012_widen_encrypted
Revises: 011_alerts_cases
Create Date: 2026-06-16

EncryptedString columns store ciphertext (~120+ chars even for short PII). The original
pan(64)/dob(32) sizes were sized to plaintext and overflow on PostgreSQL (SQLite ignores
VARCHAR length, so tests didn't catch it).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012_widen_encrypted"
down_revision: Union[str, None] = "011_alerts_cases"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return  # SQLite doesn't enforce VARCHAR length
    op.alter_column("identity_profiles", "pan", type_=sa.String(512))
    op.alter_column("identity_profiles", "dob", type_=sa.String(255))


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.alter_column("identity_profiles", "pan", type_=sa.String(64))
    op.alter_column("identity_profiles", "dob", type_=sa.String(32))
