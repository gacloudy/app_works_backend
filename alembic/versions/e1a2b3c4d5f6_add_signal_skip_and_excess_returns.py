"""add signal_skip table and excess return columns

Revision ID: e1a2b3c4d5f6
Revises: ad1445408089
Create Date: 2026-11-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1a2b3c4d5f6'
down_revision: Union[str, Sequence[str], None] = 'ad1445408089'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERIODS = [3, 5, 10, 20]

STATS_COLUMNS = [
    sa.Column('date_count', sa.Integer(), nullable=True),
    sa.Column('excess_win_rate', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('avg_excess', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('median_excess', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('avg_ind_excess', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('t_stat', sa.Numeric(precision=8, scale=3), nullable=True),
    sa.Column('first_half_excess', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('second_half_excess', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('is_consistent', sa.Boolean(), nullable=True),
    sa.Column('shrunk_excess', sa.Numeric(precision=8, scale=4), nullable=True),
]


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('signal_skip',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('code', sa.String(length=10), nullable=False),
    sa.Column('event_date', sa.Date(), nullable=False),
    sa.Column('reason', sa.String(length=30), nullable=False),
    sa.Column('detail', sa.Text(), nullable=True),
    sa.Column('ratio', sa.Numeric(precision=10, scale=4), nullable=True),
    sa.Column('change_pct', sa.Numeric(precision=8, scale=2), nullable=True),
    sa.Column('skip_from', sa.Date(), nullable=False),
    sa.Column('skip_until', sa.Date(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code', 'event_date', 'reason', name='uq_skip_code_date_reason'),
    schema='trader_schema'
    )

    for prefix in ["mkt_excess", "ind_excess"]:
        for n in PERIODS:
            op.add_column('signal_history',
                          sa.Column(f'{prefix}_{n}d', sa.Numeric(precision=8, scale=4), nullable=True),
                          schema='trader_schema')

    for col in STATS_COLUMNS:
        op.add_column('signal_stats', col.copy(), schema='trader_schema')


def downgrade() -> None:
    """Downgrade schema."""
    for col in reversed(STATS_COLUMNS):
        op.drop_column('signal_stats', col.name, schema='trader_schema')

    for prefix in ["ind_excess", "mkt_excess"]:
        for n in reversed(PERIODS):
            op.drop_column('signal_history', f'{prefix}_{n}d', schema='trader_schema')

    op.drop_table('signal_skip', schema='trader_schema')
