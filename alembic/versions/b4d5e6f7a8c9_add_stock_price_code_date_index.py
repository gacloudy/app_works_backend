"""add index on stock_price (code, trade_date)

Revision ID: b4d5e6f7a8c9
Revises: a3c4d5e6f7b8
Create Date: 2026-11-04 23:45:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b4d5e6f7a8c9'
down_revision: Union[str, Sequence[str], None] = 'a3c4d5e6f7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index('ix_stock_price_code_date', 'stock_price', ['code', 'trade_date'], unique=False, schema='trader_schema')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_stock_price_code_date', table_name='stock_price', schema='trader_schema')
