"""add_holiday_master

Revision ID: e5005b8b1867
Revises: c6d7e8f9a0b1
Create Date: 2026-06-28 22:22:18.976954

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5005b8b1867'
down_revision: Union[str, Sequence[str], None] = 'c6d7e8f9a0b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'holiday_master',
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('date'),
        schema='trader_schema',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('holiday_master', schema='trader_schema')
