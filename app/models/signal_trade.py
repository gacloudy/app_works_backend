from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Date, DateTime, Integer, Numeric, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class SignalTrade(Base):
    """シグナル1回ごとに「翌日始値で買い、N取引日後の終値で売った」場合の損益と、そのときの状況。"""
    __tablename__ = "signal_trades"
    __table_args__ = (
        UniqueConstraint("code", "signal_date", "signal_type", name="uq_signal_trades_code_date_type"),
        {"schema": "trader_schema"},
    )

    id:             Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    code:           Mapped[str]            = mapped_column(String(10), nullable=False)
    signal_date:    Mapped[date]           = mapped_column(Date, nullable=False)
    signal_type:    Mapped[str]            = mapped_column(String(50), nullable=False)
    entry_date:     Mapped[date]           = mapped_column(Date, nullable=False)          # シグナルの翌取引日
    entry_price:    Mapped[Decimal]        = mapped_column(Numeric(12, 1), nullable=False)  # 翌取引日の始値
    ret_5d:         Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)   # 始値で買い N 取引日後の終値で売った損益（%、手数料前）
    ret_10d:        Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    ret_20d:        Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    excess_5d:      Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)   # ret_Nd − 同じ日に全銘柄で同じ売買をした平均
    excess_10d:     Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    excess_20d:     Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    # ret_Nd − 同じ日・同じ区分の全銘柄の平均（ind: 業種 / scale: 規模区分 / turn: 売買代金5分位 / vol: 出来高比率）
    lift_ind_5d:    Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    lift_ind_10d:   Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    lift_ind_20d:   Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    lift_scale_5d:  Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    lift_scale_10d: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    lift_scale_20d: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    lift_turn_5d:   Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    lift_turn_10d:  Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    lift_turn_20d:  Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    lift_vol_5d:    Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    lift_vol_10d:   Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    lift_vol_20d:   Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    industry:       Mapped[str | None]     = mapped_column(String(100), nullable=True)
    scale:          Mapped[str | None]     = mapped_column(String(30), nullable=True)     # TOPIX規模区分（現在の区分）
    turnover_20d:   Mapped[Decimal | None] = mapped_column(Numeric(20, 0), nullable=True)  # 過去20日の平均売買代金（円、出来高×終値）
    turnover_q:     Mapped[int | None]     = mapped_column(SmallInteger, nullable=True)   # 同じ日の全銘柄での売買代金の5分位（1=小 〜 5=大）
    volume_ratio:   Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)   # シグナル当日の出来高 ÷ 20日平均
    volume_bucket:  Mapped[str | None]     = mapped_column(String(10), nullable=True)     # <1x / 1-2x / 2-3x / 3x+
    industry_trend: Mapped[str | None]     = mapped_column(String(10), nullable=True)     # strong / middle / weak
    regime:         Mapped[str | None]     = mapped_column(String(10), nullable=True)     # strong / neutral / weak
    updated_at:     Mapped[datetime]       = mapped_column(DateTime, default=datetime.now, nullable=False)
