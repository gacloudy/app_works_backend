"""add lift columns to signal_trades / signal_segment_stats

Revision ID: d6f7a8b9c0e1
Revises: c5e6f7a8b9d0
Create Date: 2026-11-06 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd6f7a8b9c0e1'
down_revision: Union[str, Sequence[str], None] = 'c5e6f7a8b9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LIFT_COLS = [f'lift_{k}_{n}d' for k in ['ind', 'scale', 'turn', 'vol'] for n in [5, 10, 20]]
RENAMES = [('train_excess', 'train_lift'), ('test_excess', 'test_lift'), ('shrunk_excess', 'shrunk_lift')]


def upgrade() -> None:
    """Upgrade schema."""
    for c in LIFT_COLS:
        op.add_column('signal_trades', sa.Column(c, sa.Numeric(precision=8, scale=4), nullable=True), schema='trader_schema')
    op.add_column('signal_segment_stats', sa.Column('avg_lift', sa.Numeric(precision=8, scale=4), nullable=True), schema='trader_schema')
    op.add_column('signal_segment_stats', sa.Column('lift_win_rate', sa.Numeric(precision=6, scale=2), nullable=True), schema='trader_schema')
    for old, new in RENAMES:
        op.alter_column('signal_segment_stats', old, new_column_name=new, schema='trader_schema')


def downgrade() -> None:
    """Downgrade schema."""
    for old, new in reversed(RENAMES):
        op.alter_column('signal_segment_stats', new, new_column_name=old, schema='trader_schema')
    op.drop_column('signal_segment_stats', 'lift_win_rate', schema='trader_schema')
    op.drop_column('signal_segment_stats', 'avg_lift', schema='trader_schema')
    for c in reversed(LIFT_COLS):
        op.drop_column('signal_trades', c, schema='trader_schema')
