"""add_is_delisted_to_stock_price

Revision ID: b4c5d6e7f8a9
Revises: a3f8c921bd47
Create Date: 2026-06-21 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, Sequence[str], None] = "a3f8c921bd47"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "stock_price",
        sa.Column("is_delisted", sa.Boolean(), nullable=False, server_default="false"),
        schema="trader_schema",
    )


def downgrade() -> None:
    op.drop_column("stock_price", "is_delisted", schema="trader_schema")
