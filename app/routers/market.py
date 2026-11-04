from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.industry_daily import IndustryDaily
from app.models.industry_momentum_stats import IndustryMomentumStats
from app.models.market_breadth import MarketBreadth
from app.models.signal_context_stats import SignalContextStats

router = APIRouter(prefix="/market", tags=["market"])


class BreadthItem(BaseModel):
    trade_date: date
    stock_count: int
    adv_count: int
    dec_count: int
    adv_dec_ratio_25: Decimal | None
    pct_above_ma25: Decimal | None
    avg_rsi14: Decimal | None
    mkt_return: Decimal | None
    mkt_index: Decimal | None
    regime: str | None

    model_config = {"from_attributes": True}


class IndustryItem(BaseModel):
    trade_date: date
    industry: str
    member_count: int
    return_1d: Decimal | None
    return_5d: Decimal | None
    return_20d: Decimal | None
    excess_5d: Decimal | None
    excess_20d: Decimal | None
    rank_5d: int | None
    rank_20d: int | None
    pct_above_ma25: Decimal | None

    model_config = {"from_attributes": True}


class ContextStatsItem(BaseModel):
    signal_type: str
    context_type: str
    context_value: str
    period: int
    sample_count: int
    date_count: int | None
    excess_win_rate: Decimal | None
    avg_excess: Decimal | None
    median_excess: Decimal | None
    t_stat: Decimal | None
    first_half_excess: Decimal | None
    second_half_excess: Decimal | None
    is_consistent: bool | None

    model_config = {"from_attributes": True}


class MomentumStatsItem(BaseModel):
    lookback: int
    horizon: int
    bucket: str
    date_count: int
    avg_excess: Decimal | None
    win_rate: Decimal | None
    t_stat: Decimal | None
    first_half_excess: Decimal | None
    second_half_excess: Decimal | None
    is_consistent: bool | None

    model_config = {"from_attributes": True}


@router.get("/breadth", response_model=list[BreadthItem])
def list_breadth(days: int = 120, db: Session = Depends(get_db)):
    """直近 days 取引日分の地合い指標を、古い順に返す。"""
    rows = db.query(MarketBreadth).order_by(MarketBreadth.trade_date.desc()).limit(days).all()
    return list(reversed(rows))


@router.get("/industries", response_model=list[IndustryItem])
def list_industries(trade_date: date | None = None, db: Session = Depends(get_db)):
    """指定日（省略時は最新日）の業種別の強弱を、20日の強い順に返す。"""
    if trade_date is None:
        trade_date = db.query(func.max(IndustryDaily.trade_date)).scalar()
        if trade_date is None:
            return []
    return (
        db.query(IndustryDaily)
        .filter(IndustryDaily.trade_date == trade_date)
        .order_by(IndustryDaily.rank_20d.asc().nulls_last(), IndustryDaily.industry)
        .all()
    )


@router.get("/context-stats", response_model=list[ContextStatsItem])
def list_context_stats(period: int | None = None, db: Session = Depends(get_db)):
    """シグナル × 地合い・業種の強さ別の統計を返す。"""
    q = db.query(SignalContextStats)
    if period is not None:
        q = q.filter(SignalContextStats.period == period)
    return q.order_by(
        SignalContextStats.context_type, SignalContextStats.signal_type,
        SignalContextStats.period, SignalContextStats.context_value,
    ).all()


@router.get("/industry-momentum-stats", response_model=list[MomentumStatsItem])
def list_industry_momentum_stats(db: Session = Depends(get_db)):
    """業種モメンタム（強い業種・弱い業種のその後）の検証結果を返す。"""
    return (
        db.query(IndustryMomentumStats)
        .order_by(IndustryMomentumStats.lookback, IndustryMomentumStats.horizon, IndustryMomentumStats.bucket)
        .all()
    )
