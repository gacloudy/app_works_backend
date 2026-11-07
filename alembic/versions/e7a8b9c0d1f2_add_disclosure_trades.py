"""add disclosure_trades and signal_trades.recent_disclosure

Revision ID: e7a8b9c0d1f2
Revises: d6f7a8b9c0e1
Create Date: 2026-11-07 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7a8b9c0d1f2'
down_revision: Union[str, Sequence[str], None] = 'd6f7a8b9c0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VALUE_COLS = [f'{p}_{n}d' for p in ['ret', 'excess', 'lift_ind', 'lift_scale', 'lift_turn'] for n in [5, 10, 20]]


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('disclosure_trades',
    sa.Column('disc_no', sa.String(length=20), nullable=False),
    sa.Column('code', sa.String(length=10), nullable=False),
    sa.Column('disc_date', sa.Date(), nullable=False),
    sa.Column('event', sa.String(length=50), nullable=False),
    sa.Column('change_bucket', sa.String(length=10), nullable=True),
    sa.Column('change_pct', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('base_date', sa.Date(), nullable=False),
    sa.Column('entry_date', sa.Date(), nullable=False),
    sa.Column('entry_price', sa.Numeric(precision=12, scale=1), nullable=False),
    sa.Column('gap_excess', sa.Numeric(precision=8, scale=4), nullable=True),
    *[sa.Column(c, sa.Numeric(precision=8, scale=4), nullable=True) for c in VALUE_COLS],
    sa.Column('industry', sa.String(length=100), nullable=True),
    sa.Column('scale', sa.String(length=30), nullable=True),
    sa.Column('turnover_q', sa.SmallInteger(), nullable=True),
    sa.Column('industry_trend', sa.String(length=10), nullable=True),
    sa.Column('regime', sa.String(length=10), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('disc_no'),
    schema='trader_schema'
    )
    op.add_column('signal_trades', sa.Column('recent_disclosure', sa.String(length=50), nullable=True), schema='trader_schema')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('signal_trades', 'recent_disclosure', schema='trader_schema')
    op.drop_table('disclosure_trades', schema='trader_schema')
