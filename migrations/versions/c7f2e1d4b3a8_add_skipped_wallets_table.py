"""Add skipped_wallets table

Revision ID: c7f2e1d4b3a8
Revises: a6019f7a913a
Create Date: 2026-03-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7f2e1d4b3a8'
down_revision: Union[str, Sequence[str], None] = '0e874d09a33c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'skipped_wallets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('wallet_address', sa.String(length=42), nullable=False),
        sa.Column('skips_count', sa.Integer(), nullable=False, server_default='1'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('wallet_address'),
    )


def downgrade() -> None:
    op.drop_table('skipped_wallets')
