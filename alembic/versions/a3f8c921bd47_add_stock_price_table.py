"""add_stock_price_table

Revision ID: a3f8c921bd47
Revises: 325097e4df08
Create Date: 2026-06-21 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a3f8c921bd47"
down_revision: Union[str, Sequence[str], None] = "325097e4df08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stock_price",
        sa.Column("id",            sa.Integer(),     primary_key=True, autoincrement=True),
        sa.Column("code",          sa.String(10),    nullable=False),
        sa.Column("trade_date",    sa.Date(),        nullable=False),
        sa.Column("open_price",    sa.Numeric(12, 1), nullable=True),
        sa.Column("high_price",    sa.Numeric(12, 1), nullable=True),
        sa.Column("low_price",     sa.Numeric(12, 1), nullable=True),
        sa.Column("prev_close",    sa.Numeric(12, 1), nullable=True),
        sa.Column("volume",        sa.BigInteger(),  nullable=True),
        sa.Column("current_price", sa.Numeric(12, 1), nullable=True),
        sa.Column("source",        sa.String(20),    nullable=True),
        sa.Column("created_at",    sa.DateTime(),    nullable=False),
        sa.Column("updated_at",    sa.DateTime(),    nullable=False),
        sa.UniqueConstraint("code", "trade_date", name="uq_stock_price_code_date"),
        schema="trader_schema",
    )
    op.create_index(
        "ix_stock_price_code_trade_date",
        "stock_price",
        ["code", "trade_date"],
        schema="trader_schema",
    )


def downgrade() -> None:
    op.drop_index("ix_stock_price_code_trade_date", table_name="stock_price", schema="trader_schema")
    op.drop_table("stock_price", schema="trader_schema")
