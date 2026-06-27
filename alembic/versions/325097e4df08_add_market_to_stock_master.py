"""add_market_to_stock_master

Revision ID: 325097e4df08
Revises: 3b6f46e5ad19
Create Date: 2026-06-21 16:04:52.350097

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '325097e4df08'
down_revision: Union[str, Sequence[str], None] = '3b6f46e5ad19'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("stock_master", sa.Column("market", sa.String(50), nullable=True), schema="trader_schema")


def downgrade() -> None:
    op.drop_column("stock_master", "market", schema="trader_schema")
