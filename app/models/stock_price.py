from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import BigInteger, Boolean, Date, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class StockPrice(Base):
    __tablename__ = "stock_price"
    __table_args__ = {"schema": "trader_schema"}

    id:            Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    code:          Mapped[str]            = mapped_column(String(10), nullable=False)
    trade_date:    Mapped[date]           = mapped_column(Date, nullable=False)
    open_price:    Mapped[Decimal | None] = mapped_column(Numeric(12, 1), nullable=True)
    high_price:    Mapped[Decimal | None] = mapped_column(Numeric(12, 1), nullable=True)
    low_price:     Mapped[Decimal | None] = mapped_column(Numeric(12, 1), nullable=True)
    prev_close:    Mapped[Decimal | None] = mapped_column(Numeric(12, 1), nullable=True)
    volume:        Mapped[int | None]     = mapped_column(BigInteger, nullable=True)
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 1), nullable=True)
    source:        Mapped[str | None]     = mapped_column(String(20), nullable=True)
    is_delisted:   Mapped[bool]           = mapped_column(Boolean, default=False, nullable=False)
    created_at:    Mapped[datetime]       = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at:    Mapped[datetime]       = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)
