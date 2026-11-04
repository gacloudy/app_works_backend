from datetime import datetime
from decimal import Decimal
from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class SignalContextStats(Base):
    """シグナル発生日の状況（地合い・業種の強さ）別の市場超過リターン統計。"""
    __tablename__ = "signal_context_stats"
    __table_args__ = (
        UniqueConstraint("signal_type", "context_type", "context_value", "period", name="uq_signal_context_stats"),
        {"schema": "trader_schema"},
    )

    id:                 Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_type:        Mapped[str]            = mapped_column(String(50), nullable=False)
    context_type:       Mapped[str]            = mapped_column(String(30), nullable=False)  # regime / industry_trend
    context_value:      Mapped[str]            = mapped_column(String(20), nullable=False)  # strong / neutral(middle) / weak
    period:             Mapped[int]            = mapped_column(Integer, nullable=False)     # 3, 5, 10, 20
    sample_count:       Mapped[int]            = mapped_column(Integer, nullable=False)
    date_count:         Mapped[int | None]     = mapped_column(Integer, nullable=True)
    excess_win_rate:    Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    avg_excess:         Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    median_excess:      Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    t_stat:             Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    first_half_excess:  Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    second_half_excess: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    is_consistent:      Mapped[bool | None]    = mapped_column(Boolean, nullable=True)
    updated_at:         Mapped[datetime]       = mapped_column(DateTime, default=datetime.now, nullable=False)
