"""widen token and tx columns for solana

Revision ID: a1b2c3d4e5f6
Revises: f3a1b2c9d4e5
Create Date: 2026-04-03

"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = 'f3a1b2c9d4e5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('transactions', 'token_address', type_=sa.String(64), existing_nullable=False)
    op.alter_column('transactions', 'tx_hash', type_=sa.String(100), existing_nullable=False)
    op.alter_column('alerts', 'token_address', type_=sa.String(64), existing_nullable=False)


def downgrade() -> None:
    op.alter_column('alerts', 'token_address', type_=sa.String(42), existing_nullable=False)
    op.alter_column('transactions', 'tx_hash', type_=sa.String(66), existing_nullable=False)
    op.alter_column('transactions', 'token_address', type_=sa.String(42), existing_nullable=False)
