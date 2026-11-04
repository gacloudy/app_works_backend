from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Date, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class MarketBreadth(Base):
    """取引日ごとの市場全体の地合い（騰落・25日線上比率・平均RSI など）。"""
    __tablename__ = "market_breadth"
    __table_args__ = {"schema": "trader_schema"}

    trade_date:       Mapped[date]           = mapped_column(Date, primary_key=True)
    stock_count:      Mapped[int]            = mapped_column(Integer, nullable=False)
    adv_count:        Mapped[int]            = mapped_column(Integer, nullable=False)
    dec_count:        Mapped[int]            = mapped_column(Integer, nullable=False)
    adv_dec_ratio_25: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)   # 騰落レシオ（25日）
    pct_above_ma25:   Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)   # 25日線より上の銘柄割合（%）
    avg_rsi14:        Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    mkt_return:       Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)   # 等加重平均リターン（%）
    mkt_index:        Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)  # 等加重指数（初日 = 100）
    regime:           Mapped[str | None]     = mapped_column(String(10), nullable=True)      # strong / neutral / weak
    updated_at:       Mapped[datetime]       = mapped_column(DateTime, default=datetime.now, nullable=False)
