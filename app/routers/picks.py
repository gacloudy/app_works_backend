from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.daily_pick import DailyPick
from app.models.market_breadth import MarketBreadth
from app.models.pick_result import PickResult
from app.models.stock_master import StockMaster

router = APIRouter(prefix="/picks", tags=["picks"])

RECENT_DAYS = 60


class PickItem(BaseModel):
    pick_date: date
    rank: int
    code: str
    name: str | None
    industry: str | None
    signal_type: str
    side: str
    close_price: Decimal
    hold_days: int
    past_count: int
    past_win_rate: Decimal
    past_avg: Decimal
    all_stocks_avg: Decimal | None
    score: Decimal
    is_live: bool
    # その後の結果（pick_results）
    status: str | None             # pending / holding / closed / no_data
    entry_date: date | None
    entry_price: Decimal | None
    exit_date: date | None
    exit_price: Decimal | None
    days_held: int | None
    return_pct: Decimal | None
    market_return_pct: Decimal | None
    excess_pct: Decimal | None


class DayPicks(BaseModel):
    pick_date: date | None
    trading_dates: list[date]   # 選択できる取引日（新しい順、直近 RECENT_DAYS 日）
    picks: list[PickItem]


class RecordSummary(BaseModel):
    total: int                  # 推奨の件数
    closed: int                 # 損益が確定した件数
    holding: int
    pending: int
    wins: int                   # 確定した中でプラスだった件数
    losses: int
    win_rate: float | None
    avg_return: float | None    # 確定した推奨の1回あたり平均（%）
    median_return: float | None
    best: float | None
    worst: float | None
    avg_excess: float | None    # 確定した推奨の市場との差の平均（%）
    beat_market_rate: float | None  # 市場に勝った割合（%）


class TrackRecord(BaseModel):
    live: RecordSummary         # 実際にその日に表示した推奨
    backfill: RecordSummary     # 後から同じ方法で遡って計算した推奨（参考）
    live_buy: RecordSummary
    live_sell: RecordSummary
    backfill_buy: RecordSummary
    backfill_sell: RecordSummary
    picks: list[PickItem]       # 実際に表示した推奨の全件（新しい順）


def _query(db: Session):
    return (
        db.query(DailyPick, PickResult, StockMaster.name, StockMaster.industry)
        .outerjoin(PickResult, PickResult.pick_id == DailyPick.id)
        .outerjoin(StockMaster, StockMaster.code == DailyPick.code)
    )


def _item(p: DailyPick, r: PickResult | None, name: str | None, industry: str | None) -> PickItem:
    return PickItem(
        pick_date=p.pick_date, rank=p.rank, code=p.code, name=name, industry=industry, signal_type=p.signal_type,
        side=p.side, close_price=p.close_price, hold_days=p.hold_days, past_count=p.past_count,
        past_win_rate=p.past_win_rate, past_avg=p.past_avg, all_stocks_avg=p.all_stocks_avg, score=p.score,
        is_live=p.is_live,
        status=r.status if r else None,
        entry_date=r.entry_date if r else None,
        entry_price=r.entry_price if r else None,
        exit_date=r.exit_date if r else None,
        exit_price=r.exit_price if r else None,
        days_held=r.days_held if r else None,
        return_pct=r.return_pct if r else None,
        market_return_pct=r.market_return_pct if r else None,
        excess_pct=r.excess_pct if r else None,
    )


def _summary(items: list[PickItem]) -> RecordSummary:
    closed = [i for i in items if i.status == "closed" and i.return_pct is not None]
    rets = sorted(float(i.return_pct) for i in closed)
    excess = [float(i.excess_pct) for i in closed if i.excess_pct is not None]
    n = len(rets)
    return RecordSummary(
        total=len(items),
        closed=n,
        holding=sum(i.status == "holding" for i in items),
        pending=sum(i.status == "pending" for i in items),
        wins=sum(r > 0 for r in rets),
        losses=sum(r <= 0 for r in rets),
        win_rate=round(sum(r > 0 for r in rets) / n * 100, 1) if n else None,
        avg_return=round(sum(rets) / n, 2) if n else None,
        median_return=round((rets[(n - 1) // 2] + rets[n // 2]) / 2, 2) if n else None,
        best=round(rets[-1], 2) if n else None,
        worst=round(rets[0], 2) if n else None,
        avg_excess=round(sum(excess) / len(excess), 2) if excess else None,
        beat_market_rate=round(sum(e > 0 for e in excess) / len(excess) * 100, 1) if excess else None,
    )


@router.get("", response_model=DayPicks)
def list_picks(pick_date: date | None = None, db: Session = Depends(get_db)):
    """指定日（省略時は推奨を選んだ最新日）の売買推奨と、その後の結果を返す。"""
    if pick_date is None:
        pick_date = db.query(func.max(DailyPick.pick_date)).scalar()
    trading_dates = [
        r[0] for r in db.query(MarketBreadth.trade_date).order_by(MarketBreadth.trade_date.desc()).limit(RECENT_DAYS)
    ]
    if pick_date is None:
        return DayPicks(pick_date=None, trading_dates=trading_dates, picks=[])
    rows = _query(db).filter(DailyPick.pick_date == pick_date).order_by(DailyPick.rank).all()
    return DayPicks(pick_date=pick_date, trading_dates=trading_dates, picks=[_item(*row) for row in rows])


@router.get("/track-record", response_model=TrackRecord)
def track_record(db: Session = Depends(get_db)):
    """推奨の実績。実際に表示した推奨と、遡って計算した推奨（参考）を分けて集計する。悪い結果も含めてすべて返す。"""
    items = [_item(*row) for row in _query(db).order_by(DailyPick.pick_date.desc(), DailyPick.rank).all()]
    live = [i for i in items if i.is_live]
    backfill = [i for i in items if not i.is_live]
    return TrackRecord(
        live=_summary(live),
        backfill=_summary(backfill),
        live_buy=_summary([i for i in live if i.side == "buy"]),
        live_sell=_summary([i for i in live if i.side == "sell"]),
        backfill_buy=_summary([i for i in backfill if i.side == "buy"]),
        backfill_sell=_summary([i for i in backfill if i.side == "sell"]),
        picks=live,
    )
