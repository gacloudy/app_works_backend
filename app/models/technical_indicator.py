from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Date, DateTime, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class TechnicalIndicator(Base):
    __tablename__ = "technical_indicators"
    __table_args__ = (
        UniqueConstraint("code", "trade_date", name="uq_tech_code_date"),
        {"schema": "trader_schema"},
    )

    id:           Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    code:         Mapped[str]            = mapped_column(String(10), nullable=False)
    trade_date:   Mapped[date]           = mapped_column(Date, nullable=False)
    ma5:          Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    ma25:         Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    ma75:         Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    macd:         Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    macd_signal:  Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    macd_hist:    Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    rsi14:        Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    bb_upper:     Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    bb_middle:    Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    bb_lower:     Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    volume_ma20:  Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    volume_ratio: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    created_at:   Mapped[datetime]       = mapped_column(DateTime, default=datetime.now, nullable=False)
