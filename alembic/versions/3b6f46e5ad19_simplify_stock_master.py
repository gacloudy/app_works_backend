"""simplify_stock_master

Revision ID: 3b6f46e5ad19
Revises: 
Create Date: 2026-06-21 15:59:57.869856

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3b6f46e5ad19'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("stock_master", "market",     schema="trader_schema")
    op.drop_column("stock_master", "isDelisted", schema="trader_schema")
    op.drop_column("stock_master", "note",       schema="trader_schema")
    op.drop_column("stock_master", "createdBy",  schema="trader_schema")
    op.drop_column("stock_master", "updatedBy",  schema="trader_schema")


def downgrade() -> None:
    op.add_column("stock_master", sa.Column("updatedBy",   sa.String(50),  nullable=False, server_default="default"), schema="trader_schema")
    op.add_column("stock_master", sa.Column("createdBy",   sa.String(50),  nullable=False, server_default="default"), schema="trader_schema")
    op.add_column("stock_master", sa.Column("note",        sa.Text,        nullable=True),                            schema="trader_schema")
    op.add_column("stock_master", sa.Column("isDelisted",  sa.Boolean,     nullable=False, server_default="false"),   schema="trader_schema")
    op.add_column("stock_master", sa.Column("market",      sa.String(50),  nullable=True),                            schema="trader_schema")
