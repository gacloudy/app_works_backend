from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Date, DateTime, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class SignalHistory(Base):
    __tablename__ = "signal_history"
    __table_args__ = (
        UniqueConstraint("code", "signal_date", "signal_type", name="uq_signal_code_date_type"),
        {"schema": "trader_schema"},
    )

    id:              Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    code:            Mapped[str]            = mapped_column(String(10), nullable=False)
    signal_date:     Mapped[date]           = mapped_column(Date, nullable=False)
    signal_type:     Mapped[str]            = mapped_column(String(50), nullable=False)
    detail:          Mapped[str | None]     = mapped_column(Text, nullable=True)
    price_at_signal: Mapped[Decimal | None] = mapped_column(Numeric(12, 1), nullable=True)
    return_3d:       Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    return_5d:       Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    return_10d:      Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    return_20d:      Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    created_at:      Mapped[datetime]       = mapped_column(DateTime, default=datetime.now, nullable=False)
