"""add stock_master.scale, signal_trades, signal_segment_stats

Revision ID: c5e6f7a8b9d0
Revises: b4d5e6f7a8c9
Create Date: 2026-11-06 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5e6f7a8b9d0'
down_revision: Union[str, Sequence[str], None] = 'b4d5e6f7a8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('stock_master', sa.Column('scale', sa.String(length=30), nullable=True), schema='trader_schema')

    op.create_table('signal_trades',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('code', sa.String(length=10), nullable=False),
    sa.Column('signal_date', sa.Date(), nullable=False),
    sa.Column('signal_type', sa.String(length=50), nullable=False),
    sa.Column('entry_date', sa.Date(), nullable=False),
    sa.Column('entry_price', sa.Numeric(precision=12, scale=1), nullable=False),
    *[sa.Column(f'{p}_{n}d', sa.Numeric(precision=8, scale=4), nullable=True) for p in ['ret', 'excess'] for n in [5, 10, 20]],
    sa.Column('industry', sa.String(length=100), nullable=True),
    sa.Column('scale', sa.String(length=30), nullable=True),
    sa.Column('turnover_20d', sa.Numeric(precision=20, scale=0), nullable=True),
    sa.Column('turnover_q', sa.SmallInteger(), nullable=True),
    sa.Column('volume_ratio', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('volume_bucket', sa.String(length=10), nullable=True),
    sa.Column('industry_trend', sa.String(length=10), nullable=True),
    sa.Column('regime', sa.String(length=10), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code', 'signal_date', 'signal_type', name='uq_signal_trades_code_date_type'),
    schema='trader_schema'
    )

    op.create_table('signal_segment_stats',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('signal_type', sa.String(length=50), nullable=False),
    sa.Column('segment_type', sa.String(length=30), nullable=False),
    sa.Column('segment_value', sa.String(length=100), nullable=False),
    sa.Column('period', sa.Integer(), nullable=False),
    sa.Column('sample_count', sa.Integer(), nullable=False),
    sa.Column('date_count', sa.Integer(), nullable=False),
    sa.Column('avg_net_return', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('win_rate', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('avg_excess', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('excess_win_rate', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('t_stat', sa.Numeric(precision=8, scale=3), nullable=True),
    sa.Column('train_count', sa.Integer(), nullable=True),
    sa.Column('train_excess', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('train_t', sa.Numeric(precision=8, scale=3), nullable=True),
    sa.Column('test_count', sa.Integer(), nullable=True),
    sa.Column('test_excess', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('test_t', sa.Numeric(precision=8, scale=3), nullable=True),
    sa.Column('validated', sa.Boolean(), nullable=False),
    sa.Column('shrunk_excess', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('signal_type', 'segment_type', 'segment_value', 'period', name='uq_signal_segment_stats'),
    schema='trader_schema'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('signal_segment_stats', schema='trader_schema')
    op.drop_table('signal_trades', schema='trader_schema')
    op.drop_column('stock_master', 'scale', schema='trader_schema')
