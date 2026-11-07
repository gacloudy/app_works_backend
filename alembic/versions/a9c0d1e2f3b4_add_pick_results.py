"""add pick_results

Revision ID: a9c0d1e2f3b4
Revises: f8b9c0d1e2a3
Create Date: 2026-11-07 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9c0d1e2f3b4'
down_revision: Union[str, Sequence[str], None] = 'f8b9c0d1e2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('pick_results',
    sa.Column('pick_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('entry_date', sa.Date(), nullable=True),
    sa.Column('entry_price', sa.Numeric(precision=12, scale=1), nullable=True),
    sa.Column('exit_date', sa.Date(), nullable=True),
    sa.Column('exit_price', sa.Numeric(precision=12, scale=1), nullable=True),
    sa.Column('days_held', sa.SmallInteger(), nullable=True),
    sa.Column('return_pct', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('market_return_pct', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('excess_pct', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['pick_id'], ['trader_schema.daily_picks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('pick_id'),
    schema='trader_schema'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('pick_results', schema='trader_schema')
