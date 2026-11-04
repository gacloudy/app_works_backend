from datetime import datetime
from decimal import Decimal
from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class IndustryMomentumStats(Base):
    """過去 lookback 日の上位・下位業種が、その後 horizon 日に市場に勝ったかの検証結果。"""
    __tablename__ = "industry_momentum_stats"
    __table_args__ = (
        UniqueConstraint("lookback", "horizon", "bucket", name="uq_industry_momentum_stats"),
        {"schema": "trader_schema"},
    )

    id:                 Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    lookback:           Mapped[int]            = mapped_column(Integer, nullable=False)     # 5, 20
    horizon:            Mapped[int]            = mapped_column(Integer, nullable=False)     # 5, 20
    bucket:             Mapped[str]            = mapped_column(String(10), nullable=False)  # top / bottom / spread
    date_count:         Mapped[int]            = mapped_column(Integer, nullable=False)
    avg_excess:         Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)  # 日付単位の平均市場超過リターン（%）
    win_rate:           Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    t_stat:             Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    first_half_excess:  Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    second_half_excess: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    is_consistent:      Mapped[bool | None]    = mapped_column(Boolean, nullable=True)
    updated_at:         Mapped[datetime]       = mapped_column(DateTime, default=datetime.now, nullable=False)
