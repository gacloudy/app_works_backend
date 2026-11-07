from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class PickResult(Base):
    """「今日の売買サイン」で出した推奨（daily_picks）1件ごとの、その後の実際の結果。

    推奨そのもの（daily_picks）は書き換えず、結果だけをここに記録する。悪い結果もそのまま残す。
    """
    __tablename__ = "pick_results"
    __table_args__ = {"schema": "trader_schema"}

    pick_id:           Mapped[int]            = mapped_column(
        Integer, ForeignKey("trader_schema.daily_picks.id", ondelete="CASCADE"), primary_key=True
    )
    status:            Mapped[str]            = mapped_column(String(10), nullable=False)    # pending（買付前）/ holding（保有中）/ closed（確定）/ no_data
    entry_date:        Mapped[date | None]    = mapped_column(Date, nullable=True)            # 推奨日の翌営業日
    entry_price:       Mapped[Decimal | None] = mapped_column(Numeric(12, 1), nullable=True)  # その日の始値
    exit_date:         Mapped[date | None]    = mapped_column(Date, nullable=True)            # 確定: 推奨日から hold_days 営業日後 / 保有中: 最新の取引日
    exit_price:        Mapped[Decimal | None] = mapped_column(Numeric(12, 1), nullable=True)  # その日の終値
    days_held:         Mapped[int | None]     = mapped_column(SmallInteger, nullable=True)    # 推奨日から数えた営業日数
    return_pct:        Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)   # 買い: 手数料込みの損益 / 売り: 避けられた値下がり（%）
    market_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)   # 同じ期間の市場（全銘柄の等加重指数）の騰落（%）
    excess_pct:        Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)   # 市場との差（買い: 損益 − 市場、売り: 市場 − 損益。手数料前）
    updated_at:        Mapped[datetime]       = mapped_column(DateTime, default=datetime.now, nullable=False)
