from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.signal_skip import SignalSkip
from app.models.stock_master import StockMaster

router = APIRouter(prefix="/signals", tags=["signals"])

REASON_LABELS = {
    "split_suspected": "株式分割・併合の疑い",
    "price_mismatch":  "前日終値の不一致",
    "extreme_move":    "極端な値動き",
}


class SignalSkipItem(BaseModel):
    code: str
    name: str | None
    industry: str | None
    event_date: date
    reason: str
    reason_label: str
    detail: str | None
    change_pct: Decimal | None
    skip_from: date
    skip_until: date
    is_active: bool


@router.get("/skips", response_model=list[SignalSkipItem])
def list_signal_skips(active_only: bool = False, db: Session = Depends(get_db)):
    """シグナル分析から除外している銘柄・期間・理由を、発生日の新しい順に返す。"""
    today = date.today()
    q = (
        db.query(SignalSkip, StockMaster.name, StockMaster.industry)
        .outerjoin(StockMaster, StockMaster.code == SignalSkip.code)
        .order_by(SignalSkip.event_date.desc(), SignalSkip.code)
    )
    if active_only:
        q = q.filter(SignalSkip.skip_until >= today)

    return [
        SignalSkipItem(
            code=skip.code,
            name=name,
            industry=industry,
            event_date=skip.event_date,
            reason=skip.reason,
            reason_label=REASON_LABELS.get(skip.reason, skip.reason),
            detail=skip.detail,
            change_pct=skip.change_pct,
            skip_from=skip.skip_from,
            skip_until=skip.skip_until,
            is_active=skip.skip_until >= today,
        )
        for skip, name, industry in q.all()
    ]
