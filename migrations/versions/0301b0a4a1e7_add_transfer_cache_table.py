"""Add transfer_cache table

Revision ID: 0301b0a4a1e7
Revises: 67b230228abb
Create Date: 2026-03-20 14:12:17.153876

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0301b0a4a1e7'
down_revision: Union[str, Sequence[str], None] = '67b230228abb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "transfer_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pool_address", sa.String(length=42), nullable=False),
        sa.Column("token_address", sa.String(length=42), nullable=False),
        sa.Column("chain", sa.String(length=10), nullable=False),
        sa.Column("from_dt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("to_dt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("transfers_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pool_address", "token_address", "chain"),
    )


def downgrade() -> None:
    op.drop_table("transfer_cache")
