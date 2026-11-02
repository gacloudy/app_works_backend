from datetime import datetime
from decimal import Decimal
from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, UniqueConstraint
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
    # 以下は市場超過リターン（return - 市場平均）ベースの指標
    date_count:          Mapped[int | None]     = mapped_column(Integer, nullable=True)        # シグナル発生日のユニーク数
    excess_win_rate:     Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)  # 市場に勝った割合（%）
    avg_excess:          Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    median_excess:       Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    avg_ind_excess:      Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)  # 同業種平均との差
    t_stat:              Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)  # 日付単位で集約した t 値
    first_half_excess:   Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    second_half_excess:  Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    is_consistent:       Mapped[bool | None]    = mapped_column(Boolean, nullable=True)        # 前半・後半で符号が一致
    shrunk_excess:       Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)  # 業種値を全業種値へ縮小した推定
    updated_at:    Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)
