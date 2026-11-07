from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.daily_pick import DailyPick
from app.models.market_breadth import MarketBreadth
from app.models.stock_master import StockMaster

router = APIRouter(prefix="/picks", tags=["picks"])

RECENT_DAYS = 60


class PickItem(BaseModel):
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


class DayPicks(BaseModel):
    pick_date: date | None
    trading_dates: list[date]   # 選択できる取引日（新しい順、直近 RECENT_DAYS 日）
    picks: list[PickItem]


@router.get("", response_model=DayPicks)
def list_picks(pick_date: date | None = None, db: Session = Depends(get_db)):
    """指定日（省略時は推奨を選んだ最新日）の売買推奨を返す。"""
    if pick_date is None:
        pick_date = db.query(func.max(DailyPick.pick_date)).scalar()
    trading_dates = [
        r[0] for r in db.query(MarketBreadth.trade_date).order_by(MarketBreadth.trade_date.desc()).limit(RECENT_DAYS)
    ]
    if pick_date is None:
        return DayPicks(pick_date=None, trading_dates=trading_dates, picks=[])

    rows = (
        db.query(DailyPick, StockMaster.name, StockMaster.industry)
        .outerjoin(StockMaster, StockMaster.code == DailyPick.code)
        .filter(DailyPick.pick_date == pick_date)
        .order_by(DailyPick.rank)
        .all()
    )
    return DayPicks(
        pick_date=pick_date,
        trading_dates=trading_dates,
        picks=[
            PickItem(
                rank=p.rank, code=p.code, name=name, industry=industry, signal_type=p.signal_type, side=p.side,
                close_price=p.close_price, hold_days=p.hold_days, past_count=p.past_count,
                past_win_rate=p.past_win_rate, past_avg=p.past_avg, all_stocks_avg=p.all_stocks_avg,
                score=p.score, is_live=p.is_live,
            )
            for p, name, industry in rows
        ],
    )
