from datetime import datetime
from decimal import Decimal
from sqlalchemy import DateTime, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class SignalStats(Base):
    __tablename__ = "signal_stats"
    __table_args__ = (
        # industry="" は全業種を表す
        UniqueConstraint("signal_type", "industry", "period", name="uq_stats_type_industry_period"),
        {"schema": "trader_schema"},
    )

    id:            Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_type:   Mapped[str]      = mapped_column(String(50), nullable=False)
    industry:      Mapped[str]      = mapped_column(String(100), nullable=False, default="")  # ""=全業種
    period:        Mapped[int]      = mapped_column(Integer, nullable=False)   # 3, 5, 10, 20
    sample_count:  Mapped[int]      = mapped_column(Integer, nullable=False)
    win_rate:      Mapped[Decimal]  = mapped_column(Numeric(6, 2), nullable=False)
    avg_return:    Mapped[Decimal]  = mapped_column(Numeric(8, 4), nullable=False)
    median_return: Mapped[Decimal]  = mapped_column(Numeric(8, 4), nullable=False)
    std_return:    Mapped[Decimal]  = mapped_column(Numeric(8, 4), nullable=False)
    updated_at:    Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)
