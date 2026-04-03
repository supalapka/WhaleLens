"""Widen address columns for Solana support

Revision ID: f3a1b2c9d4e5
Revises: e4ae7ea277b4
Create Date: 2026-04-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f3a1b2c9d4e5'
down_revision: Union[str, None] = 'e4ae7ea277b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('wallets', 'address', type_=sa.String(64), existing_type=sa.String(42))
    op.alter_column('wallet_detections', 'wallet_address', type_=sa.String(64), existing_type=sa.String(42))
    op.alter_column('wallet_detections', 'token_address', type_=sa.String(64), existing_type=sa.String(42))
    op.alter_column('transfer_cache', 'pool_address', type_=sa.String(64), existing_type=sa.String(42))
    op.alter_column('transfer_cache', 'token_address', type_=sa.String(64), existing_type=sa.String(42))


def downgrade() -> None:
    op.alter_column('transfer_cache', 'token_address', type_=sa.String(42), existing_type=sa.String(64))
    op.alter_column('transfer_cache', 'pool_address', type_=sa.String(42), existing_type=sa.String(64))
    op.alter_column('wallet_detections', 'token_address', type_=sa.String(42), existing_type=sa.String(64))
    op.alter_column('wallet_detections', 'wallet_address', type_=sa.String(42), existing_type=sa.String(64))
    op.alter_column('wallets', 'address', type_=sa.String(42), existing_type=sa.String(64))
