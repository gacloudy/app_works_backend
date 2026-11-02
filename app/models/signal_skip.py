from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Date, DateTime, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class SignalSkip(Base):
    """株式分割・極端な値動きなどで、シグナル分析から除外する銘柄と期間。"""
    __tablename__ = "signal_skip"
    __table_args__ = (
        UniqueConstraint("code", "event_date", "reason", name="uq_skip_code_date_reason"),
        {"schema": "trader_schema"},
    )

    id:         Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    code:       Mapped[str]            = mapped_column(String(10), nullable=False)
    event_date: Mapped[date]           = mapped_column(Date, nullable=False)
    reason:     Mapped[str]            = mapped_column(String(30), nullable=False)  # split_suspected / price_mismatch / extreme_move
    detail:     Mapped[str | None]     = mapped_column(Text, nullable=True)
    ratio:      Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)  # 前日終値(取得元) ÷ 前日終値(保存値)
    change_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)   # 保存済み前日終値からの騰落率(%)
    skip_from:  Mapped[date]           = mapped_column(Date, nullable=False)
    skip_until: Mapped[date]           = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime]       = mapped_column(DateTime, default=datetime.now, nullable=False)
