from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Date, DateTime, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class IndustryDaily(Base):
    """取引日 × 33業種ごとの業種指数と、市場に対する強弱。"""
    __tablename__ = "industry_daily"
    __table_args__ = (
        UniqueConstraint("trade_date", "industry", name="uq_industry_daily_date_industry"),
        {"schema": "trader_schema"},
    )

    id:             Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date:     Mapped[date]           = mapped_column(Date, nullable=False)
    industry:       Mapped[str]            = mapped_column(String(100), nullable=False)
    member_count:   Mapped[int]            = mapped_column(Integer, nullable=False)
    return_1d:      Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)   # 等加重平均リターン（%）
    index_value:    Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)  # 業種指数（初日 = 100）
    return_5d:      Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    return_20d:     Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    excess_5d:      Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)   # 市場指数との差（%）
    excess_20d:     Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    rank_5d:        Mapped[int | None]     = mapped_column(Integer, nullable=True)         # 1 = 最も強い
    rank_20d:       Mapped[int | None]     = mapped_column(Integer, nullable=True)
    pct_above_ma25: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    updated_at:     Mapped[datetime]       = mapped_column(DateTime, default=datetime.now, nullable=False)
