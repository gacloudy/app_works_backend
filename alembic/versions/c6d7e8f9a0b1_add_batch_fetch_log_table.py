"""add_batch_fetch_log_table

Revision ID: c6d7e8f9a0b1
Revises: b4c5d6e7f8a9
Create Date: 2026-06-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c6d7e8f9a0b1"
down_revision: Union[str, Sequence[str], None] = "b4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "batch_fetch_log",
        sa.Column("id",         sa.Integer(),     nullable=False, autoincrement=True),
        sa.Column("run_id",     sa.String(20),    nullable=False),
        sa.Column("code",       sa.String(10),    nullable=False),
        sa.Column("status",     sa.String(10),    nullable=False),
        sa.Column("reason",     sa.String(100),   nullable=False),
        sa.Column("source",     sa.String(20),    nullable=True),
        sa.Column("created_at", sa.DateTime(),    nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="trader_schema",
    )
    op.create_index(
        "ix_batch_fetch_log_run_id",
        "batch_fetch_log",
        ["run_id"],
        schema="trader_schema",
    )
    op.create_index(
        "ix_batch_fetch_log_code",
        "batch_fetch_log",
        ["code"],
        schema="trader_schema",
    )


def downgrade() -> None:
    op.drop_index("ix_batch_fetch_log_code",   table_name="batch_fetch_log", schema="trader_schema")
    op.drop_index("ix_batch_fetch_log_run_id", table_name="batch_fetch_log", schema="trader_schema")
    op.drop_table("batch_fetch_log", schema="trader_schema")
