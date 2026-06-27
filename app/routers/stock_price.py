from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.stock_price import StockPrice

router = APIRouter(prefix="/stock-price", tags=["stock-price"])


class LatestPrice(BaseModel):
    code: str
    current_price: Decimal | None
    trade_date: date


class StockPriceDetail(BaseModel):
    code: str
    trade_date: date
    current_price: Decimal | None
    open_price: Decimal | None
    high_price: Decimal | None
    low_price: Decimal | None
    prev_close: Decimal | None
    volume: int | None

    model_config = {"from_attributes": True}


@router.get("/latest", response_model=dict[str, LatestPrice])
def get_latest_prices(db: Session = Depends(get_db)):
    """全銘柄の最新取引日の株価を返す。{code: {current_price, trade_date}} 形式。"""
    subq = (
        db.query(
            StockPrice.code,
            func.max(StockPrice.trade_date).label("max_date"),
        )
        .filter(StockPrice.is_delisted == False)  # noqa: E712
        .group_by(StockPrice.code)
        .subquery()
    )

    rows = (
        db.query(StockPrice)
        .join(
            subq,
            (StockPrice.code == subq.c.code)
            & (StockPrice.trade_date == subq.c.max_date),
        )
        .all()
    )

    return {
        row.code: LatestPrice(
            code=row.code,
            current_price=row.current_price,
            trade_date=row.trade_date,
        )
        for row in rows
    }


@router.get("/{code}/history", response_model=list[StockPriceDetail])
def get_price_history(code: str, days: int = 60, db: Session = Depends(get_db)):
    """指定銘柄の直近 days 件の株価を昇順で返す。"""
    rows = (
        db.query(StockPrice)
        .filter(StockPrice.code == code, StockPrice.is_delisted == False)  # noqa: E712
        .order_by(StockPrice.trade_date.desc())
        .limit(days)
        .all()
    )
    return list(reversed(rows))


@router.get("/{code}/latest", response_model=StockPriceDetail)
def get_latest_price_by_code(code: str, db: Session = Depends(get_db)):
    """指定銘柄の最新取引日の株価を返す。"""
    row = (
        db.query(StockPrice)
        .filter(StockPrice.code == code, StockPrice.is_delisted == False)  # noqa: E712
        .order_by(StockPrice.trade_date.desc())
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="株価データがありません")
    return row
