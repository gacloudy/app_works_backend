"""add daily_picks

Revision ID: f8b9c0d1e2a3
Revises: e7a8b9c0d1f2
Create Date: 2026-11-07 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f8b9c0d1e2a3'
down_revision: Union[str, Sequence[str], None] = 'e7a8b9c0d1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('daily_picks',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('pick_date', sa.Date(), nullable=False),
    sa.Column('rank', sa.SmallInteger(), nullable=False),
    sa.Column('code', sa.String(length=10), nullable=False),
    sa.Column('signal_type', sa.String(length=50), nullable=False),
    sa.Column('side', sa.String(length=4), nullable=False),
    sa.Column('close_price', sa.Numeric(precision=12, scale=1), nullable=False),
    sa.Column('hold_days', sa.SmallInteger(), nullable=False),
    sa.Column('past_count', sa.Integer(), nullable=False),
    sa.Column('past_win_rate', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('past_avg', sa.Numeric(precision=8, scale=4), nullable=False),
    sa.Column('all_stocks_avg', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('score', sa.Numeric(precision=8, scale=4), nullable=False),
    sa.Column('is_live', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('pick_date', 'rank', name='uq_daily_picks_date_rank'),
    schema='trader_schema'
    )
    op.create_index('ix_daily_picks_code', 'daily_picks', ['code'], unique=False, schema='trader_schema')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_daily_picks_code', table_name='daily_picks', schema='trader_schema')
    op.drop_table('daily_picks', schema='trader_schema')
