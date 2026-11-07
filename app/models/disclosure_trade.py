from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Date, DateTime, Numeric, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class DisclosureTrade(Base):
    """決算・予想修正の開示ごとに「開示後に最初に買える始値で買い、N 取引日後の終値で売った」場合の損益と、そのときの状況。"""
    __tablename__ = "disclosure_trades"
    __table_args__ = {"schema": "trader_schema"}

    disc_no:        Mapped[str]            = mapped_column(String(20), primary_key=True)
    code:           Mapped[str]            = mapped_column(String(10), nullable=False)
    disc_date:      Mapped[date]           = mapped_column(Date, nullable=False)
    event:          Mapped[str]            = mapped_column(String(50), nullable=False)   # "<event_type>_<direction>"（例: earn_revision_up）
    change_bucket:  Mapped[str | None]     = mapped_column(String(10), nullable=True)    # large（|変化率| >= 10%）/ small / flat
    change_pct:     Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    base_date:      Mapped[date]           = mapped_column(Date, nullable=False)          # 買う前日（signal_trades の signal_date に相当）
    entry_date:     Mapped[date]           = mapped_column(Date, nullable=False)
    entry_price:    Mapped[Decimal]        = mapped_column(Numeric(12, 1), nullable=False)
    gap_excess:     Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)  # 開示前の終値 → 買う日の始値（市場比、%）。買えない部分の反応
    ret_5d:         Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    ret_10d:        Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    ret_20d:        Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    excess_5d:      Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    excess_10d:     Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    excess_20d:     Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    lift_ind_5d:    Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    lift_ind_10d:   Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    lift_ind_20d:   Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    lift_scale_5d:  Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    lift_scale_10d: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    lift_scale_20d: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    lift_turn_5d:   Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    lift_turn_10d:  Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    lift_turn_20d:  Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    industry:       Mapped[str | None]     = mapped_column(String(100), nullable=True)
    scale:          Mapped[str | None]     = mapped_column(String(30), nullable=True)
    turnover_q:     Mapped[int | None]     = mapped_column(SmallInteger, nullable=True)
    industry_trend: Mapped[str | None]     = mapped_column(String(10), nullable=True)
    regime:         Mapped[str | None]     = mapped_column(String(10), nullable=True)
    updated_at:     Mapped[datetime]       = mapped_column(DateTime, default=datetime.now, nullable=False)
