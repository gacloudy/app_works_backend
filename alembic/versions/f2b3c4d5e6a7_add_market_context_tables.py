"""add market_breadth, industry_daily, signal_context_stats, industry_momentum_stats

Revision ID: f2b3c4d5e6a7
Revises: e1a2b3c4d5f6
Create Date: 2026-11-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2b3c4d5e6a7'
down_revision: Union[str, Sequence[str], None] = 'e1a2b3c4d5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('market_breadth',
    sa.Column('trade_date', sa.Date(), nullable=False),
    sa.Column('stock_count', sa.Integer(), nullable=False),
    sa.Column('adv_count', sa.Integer(), nullable=False),
    sa.Column('dec_count', sa.Integer(), nullable=False),
    sa.Column('adv_dec_ratio_25', sa.Numeric(precision=8, scale=2), nullable=True),
    sa.Column('pct_above_ma25', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('avg_rsi14', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('mkt_return', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('mkt_index', sa.Numeric(precision=12, scale=4), nullable=True),
    sa.Column('regime', sa.String(length=10), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('trade_date'),
    schema='trader_schema'
    )
    op.create_table('industry_daily',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('trade_date', sa.Date(), nullable=False),
    sa.Column('industry', sa.String(length=100), nullable=False),
    sa.Column('member_count', sa.Integer(), nullable=False),
    sa.Column('return_1d', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('index_value', sa.Numeric(precision=12, scale=4), nullable=True),
    sa.Column('return_5d', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('return_20d', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('excess_5d', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('excess_20d', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('rank_5d', sa.Integer(), nullable=True),
    sa.Column('rank_20d', sa.Integer(), nullable=True),
    sa.Column('pct_above_ma25', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('trade_date', 'industry', name='uq_industry_daily_date_industry'),
    schema='trader_schema'
    )
    op.create_table('signal_context_stats',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('signal_type', sa.String(length=50), nullable=False),
    sa.Column('context_type', sa.String(length=30), nullable=False),
    sa.Column('context_value', sa.String(length=20), nullable=False),
    sa.Column('period', sa.Integer(), nullable=False),
    sa.Column('sample_count', sa.Integer(), nullable=False),
    sa.Column('date_count', sa.Integer(), nullable=True),
    sa.Column('excess_win_rate', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('avg_excess', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('median_excess', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('t_stat', sa.Numeric(precision=8, scale=3), nullable=True),
    sa.Column('first_half_excess', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('second_half_excess', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('is_consistent', sa.Boolean(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('signal_type', 'context_type', 'context_value', 'period', name='uq_signal_context_stats'),
    schema='trader_schema'
    )
    op.create_table('industry_momentum_stats',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('lookback', sa.Integer(), nullable=False),
    sa.Column('horizon', sa.Integer(), nullable=False),
    sa.Column('bucket', sa.String(length=10), nullable=False),
    sa.Column('date_count', sa.Integer(), nullable=False),
    sa.Column('avg_excess', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('win_rate', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('t_stat', sa.Numeric(precision=8, scale=3), nullable=True),
    sa.Column('first_half_excess', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('second_half_excess', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('is_consistent', sa.Boolean(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('lookback', 'horizon', 'bucket', name='uq_industry_momentum_stats'),
    schema='trader_schema'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('industry_momentum_stats', schema='trader_schema')
    op.drop_table('signal_context_stats', schema='trader_schema')
    op.drop_table('industry_daily', schema='trader_schema')
    op.drop_table('market_breadth', schema='trader_schema')
