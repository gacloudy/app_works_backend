from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Boolean, Date, DateTime, Index, Integer, Numeric, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class DailyPick(Base):
    """終値確定後に選んだ「翌営業日の買い時・売り時」の推奨（1日最大 MAX_PICKS 件）。

    選定に使う成績は、pick_date までに結果が確定していた過去のシグナルだけで計算する（未来のデータは使わない）。
    """
    __tablename__ = "daily_picks"
    __table_args__ = (
        UniqueConstraint("pick_date", "rank", name="uq_daily_picks_date_rank"),
        Index("ix_daily_picks_code", "code"),
        {"schema": "trader_schema"},
    )

    id:             Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    pick_date:      Mapped[date]           = mapped_column(Date, nullable=False)          # シグナルが出た日（この日の終値確定後に表示）
    rank:           Mapped[int]            = mapped_column(SmallInteger, nullable=False)  # 1 〜 MAX_PICKS
    code:           Mapped[str]            = mapped_column(String(10), nullable=False)
    signal_type:    Mapped[str]            = mapped_column(String(50), nullable=False)
    side:           Mapped[str]            = mapped_column(String(4), nullable=False)     # buy / sell
    close_price:    Mapped[Decimal]        = mapped_column(Numeric(12, 1), nullable=False)  # pick_date の終値
    hold_days:      Mapped[int]            = mapped_column(SmallInteger, nullable=False)  # 想定保有日数（翌営業日始値 → N 営業日後の終値）
    past_count:     Mapped[int]            = mapped_column(Integer, nullable=False)       # この銘柄でこのサインの結果が確定していた回数
    past_win_rate:  Mapped[Decimal]        = mapped_column(Numeric(6, 2), nullable=False)
    past_avg:       Mapped[Decimal]        = mapped_column(Numeric(8, 4), nullable=False)  # 1回平均（買い: 手数料込みの損益、売り: 避けられた値下がり、%）
    all_stocks_avg: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)   # 同じ時点の全銘柄での同じサインの1回平均
    score:          Mapped[Decimal]        = mapped_column(Numeric(8, 4), nullable=False)  # 回数で全銘柄平均に寄せた1回平均（並べ順）
    is_live:        Mapped[bool]           = mapped_column(Boolean, nullable=False)       # true: その日の夜に実際に選んだ / false: 後から同じ方法で遡って計算した
    created_at:     Mapped[datetime]       = mapped_column(DateTime, default=datetime.now, nullable=False)
