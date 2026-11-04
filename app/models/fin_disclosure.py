from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Date, DateTime, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class FinDisclosure(Base):
    """J-Quants /fins/summary から取得した決算短信・業績予想の修正・配当予想の修正と、開示後の株価反応。"""
    __tablename__ = "fin_disclosure"
    __table_args__ = (
        Index("ix_fin_disclosure_code_date", "code", "disc_date"),
        {"schema": "trader_schema"},
    )

    disc_no:      Mapped[str]         = mapped_column(String(20), primary_key=True)  # 開示番号
    code:         Mapped[str]         = mapped_column(String(10), nullable=False)
    disc_date:    Mapped[date]        = mapped_column(Date, nullable=False)
    disc_time:    Mapped[str]         = mapped_column(String(5), nullable=False)     # HH:MM
    doc_type:     Mapped[str]         = mapped_column(String(80), nullable=False)    # J-Quants の開示書類種別
    cur_per_type: Mapped[str | None]  = mapped_column(String(5), nullable=True)      # 1Q/2Q/3Q/4Q/5Q/FY
    cur_fy_st:    Mapped[date | None] = mapped_column(Date, nullable=True)
    cur_fy_en:    Mapped[date | None] = mapped_column(Date, nullable=True)
    nxt_fy_st:    Mapped[date | None] = mapped_column(Date, nullable=True)
    nxt_fy_en:    Mapped[date | None] = mapped_column(Date, nullable=True)
    # 実績・予想（円。配当は1株あたり円）。f_ = 当事業年度の予想、nx_f_ = 翌事業年度の予想
    sales:        Mapped[Decimal | None] = mapped_column(Numeric(20, 0), nullable=True)
    op:           Mapped[Decimal | None] = mapped_column(Numeric(20, 0), nullable=True)
    odp:          Mapped[Decimal | None] = mapped_column(Numeric(20, 0), nullable=True)
    np:           Mapped[Decimal | None] = mapped_column(Numeric(20, 0), nullable=True)
    f_sales:      Mapped[Decimal | None] = mapped_column(Numeric(20, 0), nullable=True)
    f_op:         Mapped[Decimal | None] = mapped_column(Numeric(20, 0), nullable=True)
    f_odp:        Mapped[Decimal | None] = mapped_column(Numeric(20, 0), nullable=True)
    f_np:         Mapped[Decimal | None] = mapped_column(Numeric(20, 0), nullable=True)
    nx_f_sales:   Mapped[Decimal | None] = mapped_column(Numeric(20, 0), nullable=True)
    nx_f_op:      Mapped[Decimal | None] = mapped_column(Numeric(20, 0), nullable=True)
    nx_f_odp:     Mapped[Decimal | None] = mapped_column(Numeric(20, 0), nullable=True)
    nx_f_np:      Mapped[Decimal | None] = mapped_column(Numeric(20, 0), nullable=True)
    div_ann:      Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    f_div_ann:    Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    nx_f_div_ann: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    fetched_at:   Mapped[datetime]       = mapped_column(DateTime, default=datetime.now, nullable=False)
    # 以下は update_disclosure_results バッチが計算する
    event_type:      Mapped[str | None]     = mapped_column(String(30), nullable=True)    # fy_results / q_results / earn_revision / div_revision
    metric:          Mapped[str | None]     = mapped_column(String(10), nullable=True)    # 比較に使った項目（op / odp / np / div）
    base_value:      Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)  # 比較元（前回予想、FY決算は当期実績）
    new_value:       Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)  # 今回の予想
    change_pct:      Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)  # (new − base) / |base| × 100
    direction:       Mapped[str | None]     = mapped_column(String(10), nullable=True)    # up / down / flat
    reaction_date:   Mapped[date | None]    = mapped_column(Date, nullable=True)          # 株価が開示に反応できる最初の取引日
    reaction_excess: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)  # 反応日の市場超過リターン（%）
    drift_5d:        Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)  # 反応日終値から5取引日後までの市場超過リターン（%）
    drift_20d:       Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
