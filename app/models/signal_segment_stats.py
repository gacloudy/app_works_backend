from datetime import datetime
from decimal import Decimal
from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class SignalSegmentStats(Base):
    """シグナル × 切り口（規模・売買代金・出来高・業種など）ごとの売買成績と、期間を分けた検証結果。

    lift = 同じ日・同じ区分の全銘柄の平均との差（区分そのものの強弱を除いた、シグナルの上乗せ分）。
    t 値・探索/検証期間の値・validated はすべて lift で計算する。
    """
    __tablename__ = "signal_segment_stats"
    __table_args__ = (
        UniqueConstraint("signal_type", "segment_type", "segment_value", "period", name="uq_signal_segment_stats"),
        {"schema": "trader_schema"},
    )

    id:              Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_type:     Mapped[str]            = mapped_column(String(50), nullable=False)
    segment_type:    Mapped[str]            = mapped_column(String(30), nullable=False)   # all / industry / scale / turnover / volume / industry_trend / regime / scale_volume / code
    segment_value:   Mapped[str]            = mapped_column(String(100), nullable=False)  # all のときは ""
    period:          Mapped[int]            = mapped_column(Integer, nullable=False)      # 5, 10, 20
    sample_count:    Mapped[int]            = mapped_column(Integer, nullable=False)
    date_count:      Mapped[int]            = mapped_column(Integer, nullable=False)
    avg_net_return:  Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)  # 手数料（往復）差し引き後の1回あたり平均損益（%）
    win_rate:        Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)  # 手数料差し引き後にプラスだった割合（%）
    avg_excess:      Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)  # 市場平均との差（%）。区分そのものの強弱を含む
    excess_win_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    avg_lift:        Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)  # 同じ日・同じ区分の平均との差（%）
    lift_win_rate:   Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    t_stat:          Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)  # 日付ごとの平均を1サンプルとした avg_lift の t 値
    train_count:     Mapped[int | None]     = mapped_column(Integer, nullable=True)        # 探索期間（〜TRAIN_END）
    train_lift:      Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    train_t:         Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    test_count:      Mapped[int | None]     = mapped_column(Integer, nullable=True)        # 検証期間（TRAIN_END の翌日〜）
    test_lift:       Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    test_t:          Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    validated:       Mapped[bool]           = mapped_column(Boolean, nullable=False, default=False)  # 探索期間で見つかり、検証期間でも同じ向きに成り立った
    shrunk_lift:     Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)  # 件数が少ない切り口（銘柄・業種）を全体の値へ寄せた推定値
    updated_at:      Mapped[datetime]       = mapped_column(DateTime, default=datetime.now, nullable=False)
