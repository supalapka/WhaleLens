"""Add always_alert to wallets

Revision ID: d9e3f2a1b4c0
Revises: c7f2e1d4b3a8
Create Date: 2026-03-26 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd9e3f2a1b4c0'
down_revision: Union[str, Sequence[str], None] = 'c7f2e1d4b3a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('wallets', sa.Column('always_alert', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    op.drop_column('wallets', 'always_alert')
