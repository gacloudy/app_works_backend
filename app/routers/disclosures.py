from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.fin_disclosure import FinDisclosure
from app.models.stock_master import StockMaster

router = APIRouter(prefix="/disclosures", tags=["disclosures"])

MIN_SAMPLES = 5


class DisclosureStatsItem(BaseModel):
    event_type: str
    direction: str
    sample_count: int
    date_count: int
    avg_reaction: float | None   # 反応日の平均市場超過リターン（%）
    reaction_win_rate: float | None
    avg_drift_5d: float | None
    avg_drift_20d: float | None
    drift_20d_count: int
    drift_20d_t_stat: float | None  # 日付ごとの平均を1サンプルとした t 値


class DisclosureItem(BaseModel):
    disc_no: str
    code: str
    name: str | None
    industry: str | None
    disc_date: date
    disc_time: str
    event_type: str
    direction: str | None
    metric: str | None
    change_pct: Decimal | None
    reaction_date: date | None
    reaction_excess: Decimal | None
    drift_5d: Decimal | None
    drift_20d: Decimal | None


def _mean(s: pd.Series) -> float | None:
    s = s.dropna()
    return round(float(s.mean()), 4) if len(s) else None


def _date_t_stat(df: pd.DataFrame, col: str) -> float | None:
    by_date = df.dropna(subset=[col]).groupby("reaction_date")[col].mean()
    if len(by_date) < 3 or by_date.std() == 0:
        return None
    return round(float(by_date.mean() / (by_date.std() / np.sqrt(len(by_date)))), 3)


@router.get("/stats", response_model=list[DisclosureStatsItem])
def disclosure_stats(db: Session = Depends(get_db)):
    """開示の種類 × 方向（上方/下方/据え置き）ごとに、開示後の株価の反応を集計する。"""
    rows = (
        db.query(
            FinDisclosure.event_type, FinDisclosure.direction, FinDisclosure.reaction_date,
            FinDisclosure.reaction_excess, FinDisclosure.drift_5d, FinDisclosure.drift_20d,
        )
        .filter(FinDisclosure.direction.isnot(None), FinDisclosure.reaction_excess.isnot(None))
        .all()
    )
    if not rows:
        return []
    df = pd.DataFrame(rows, columns=["event_type", "direction", "reaction_date", "reaction_excess", "drift_5d", "drift_20d"])
    for c in ["reaction_excess", "drift_5d", "drift_20d"]:
        df[c] = df[c].astype(float)

    items = []
    for (event_type, direction), g in df.groupby(["event_type", "direction"]):
        if len(g) < MIN_SAMPLES:
            continue
        items.append(DisclosureStatsItem(
            event_type=event_type,
            direction=direction,
            sample_count=len(g),
            date_count=int(g["reaction_date"].nunique()),
            avg_reaction=_mean(g["reaction_excess"]),
            reaction_win_rate=round(float((g["reaction_excess"] > 0).mean() * 100), 2),
            avg_drift_5d=_mean(g["drift_5d"]),
            avg_drift_20d=_mean(g["drift_20d"]),
            drift_20d_count=int(g["drift_20d"].notna().sum()),
            drift_20d_t_stat=_date_t_stat(g, "drift_20d"),
        ))
    return items


@router.get("/recent", response_model=list[DisclosureItem])
def recent_disclosures(limit: int = 100, direction: str | None = None, db: Session = Depends(get_db)):
    """分類済みの開示を新しい順に返す。"""
    q = (
        db.query(FinDisclosure, StockMaster.name, StockMaster.industry)
        .outerjoin(StockMaster, StockMaster.code == FinDisclosure.code)
        .filter(FinDisclosure.event_type.isnot(None))
    )
    if direction:
        q = q.filter(FinDisclosure.direction == direction)
    q = q.order_by(FinDisclosure.disc_date.desc(), FinDisclosure.disc_time.desc()).limit(limit)
    return [
        DisclosureItem(
            disc_no=d.disc_no, code=d.code, name=name, industry=industry,
            disc_date=d.disc_date, disc_time=d.disc_time, event_type=d.event_type,
            direction=d.direction, metric=d.metric, change_pct=d.change_pct,
            reaction_date=d.reaction_date, reaction_excess=d.reaction_excess,
            drift_5d=d.drift_5d, drift_20d=d.drift_20d,
        )
        for d, name, industry in q.all()
    ]
