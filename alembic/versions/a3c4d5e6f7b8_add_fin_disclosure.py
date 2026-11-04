"""add fin_disclosure

Revision ID: a3c4d5e6f7b8
Revises: f2b3c4d5e6a7
Create Date: 2026-11-04 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3c4d5e6f7b8'
down_revision: Union[str, Sequence[str], None] = 'f2b3c4d5e6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

AMOUNT_COLUMNS = [
    'sales', 'op', 'odp', 'np', 'f_sales', 'f_op', 'f_odp', 'f_np',
    'nx_f_sales', 'nx_f_op', 'nx_f_odp', 'nx_f_np',
]
DIVIDEND_COLUMNS = ['div_ann', 'f_div_ann', 'nx_f_div_ann']


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('fin_disclosure',
    sa.Column('disc_no', sa.String(length=20), nullable=False),
    sa.Column('code', sa.String(length=10), nullable=False),
    sa.Column('disc_date', sa.Date(), nullable=False),
    sa.Column('disc_time', sa.String(length=5), nullable=False),
    sa.Column('doc_type', sa.String(length=80), nullable=False),
    sa.Column('cur_per_type', sa.String(length=5), nullable=True),
    sa.Column('cur_fy_st', sa.Date(), nullable=True),
    sa.Column('cur_fy_en', sa.Date(), nullable=True),
    sa.Column('nxt_fy_st', sa.Date(), nullable=True),
    sa.Column('nxt_fy_en', sa.Date(), nullable=True),
    *[sa.Column(c, sa.Numeric(precision=20, scale=0), nullable=True) for c in AMOUNT_COLUMNS],
    *[sa.Column(c, sa.Numeric(precision=12, scale=2), nullable=True) for c in DIVIDEND_COLUMNS],
    sa.Column('fetched_at', sa.DateTime(), nullable=False),
    sa.Column('event_type', sa.String(length=30), nullable=True),
    sa.Column('metric', sa.String(length=10), nullable=True),
    sa.Column('base_value', sa.Numeric(precision=20, scale=2), nullable=True),
    sa.Column('new_value', sa.Numeric(precision=20, scale=2), nullable=True),
    sa.Column('change_pct', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('direction', sa.String(length=10), nullable=True),
    sa.Column('reaction_date', sa.Date(), nullable=True),
    sa.Column('reaction_excess', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('drift_5d', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('drift_20d', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.PrimaryKeyConstraint('disc_no'),
    schema='trader_schema'
    )
    op.create_index('ix_fin_disclosure_code_date', 'fin_disclosure', ['code', 'disc_date'], unique=False, schema='trader_schema')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_fin_disclosure_code_date', table_name='fin_disclosure', schema='trader_schema')
    op.drop_table('fin_disclosure', schema='trader_schema')
