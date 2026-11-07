"""
決算・予想修正の開示（fin_disclosure）ごとに「開示後に最初に買える始値で買い、N 取引日後の終値で売った」場合の損益と、
そのときの状況を disclosure_trades に保存するバッチ。update_disclosure_results と calc_market_context の後に実行する。

  entry_date : 開示後に最初に始値で買える取引日。9:00 より前の開示は当日、それ以降は翌取引日
  base_date  : entry_date の前の取引日。損益・市場比・上乗せは calc_signal_trades と同じ計算で、
               「base_date にシグナルが出て翌日始値で買った」ものとして求める
  gap_excess : base_date の終値 → entry_date の始値（市場比、%）。開示に反応して寄り付きまでに動いた分で、買うことはできない
  event      : "<event_type>_<direction>"（例: earn_revision_up、fy_results_down）
  change_bucket : 変化率の大きさ。|change_pct| >= LARGE_CHANGE_PCT なら large、それ以外は small（flat は flat）

毎回全件を作り直す（冪等）。

実行方法:
    cd app_works_backend
    .venv\\Scripts\\python batch\\calc_disclosure_trades.py
"""

import sys
import os
import bisect
import logging
from datetime import datetime

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv()

from app.database import SessionLocal
from app.models.disclosure_trade import DisclosureTrade
from batch.aggregate_context_stats import industry_trend_of
from batch.calc_signal_trades import PERIODS, calc_price_features, load_prices
from batch.signal_skip_util import load_skip_windows, skipped_mask

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

MARKET_OPEN = "09:00"
LARGE_CHANGE_PCT = 10.0
VALUE_COLS = [f"{p}_{n}d" for p in ["ret", "excess", "lift_ind", "lift_scale", "lift_turn"] for n in PERIODS]


def change_bucket_of(direction: str, change_pct: float | None) -> str | None:
    if direction == "flat":
        return "flat"
    if change_pct is None or np.isnan(change_pct):
        return None
    return "large" if abs(change_pct) >= LARGE_CHANGE_PCT else "small"


def main() -> None:
    start = datetime.now()
    log.info("=== 開示の取引損益計算バッチ 開始 ===")

    with SessionLocal() as db:
        disc = pd.read_sql(text("""
            SELECT d.disc_no, d.code, d.disc_date, d.disc_time, d.event_type, d.direction, d.change_pct
            FROM trader_schema.fin_disclosure d
            JOIN trader_schema.stock_master sm ON sm.code = d.code
            WHERE d.direction IS NOT NULL
        """), db.connection())
        prices = load_prices(db)
        regimes = pd.read_sql(text("SELECT trade_date, regime FROM trader_schema.market_breadth ORDER BY trade_date"),
                              db.connection())
        industries = pd.read_sql(text("SELECT trade_date, industry, rank_20d FROM trader_schema.industry_daily"),
                                 db.connection())
        skip_windows = load_skip_windows(db)

    if disc.empty:
        log.info("分類済みの開示なし")
        log.info("=== 開示の取引損益計算バッチ 終了 ===")
        return
    log.info("開示: %d 件 / 株価: %d 行", len(disc), len(prices))

    # 開示後に最初に買える取引日（entry_date）と、その前の取引日（base_date）
    trading_days = list(pd.to_datetime(regimes["trade_date"]).dt.date)
    disc["disc_date"] = pd.to_datetime(disc["disc_date"]).dt.date
    base_dates = []
    for d, t in zip(disc["disc_date"], disc["disc_time"]):
        pos = bisect.bisect_left(trading_days, d)
        if pos < len(trading_days) and trading_days[pos] == d and t >= MARKET_OPEN:
            pos += 1
        base_dates.append(trading_days[pos - 1] if 0 < pos < len(trading_days) else None)
    disc["base_date"] = base_dates
    disc = disc.dropna(subset=["base_date"])

    feats = calc_price_features(prices, skip_windows)
    feats["gap"] = (feats["entry_price"] / feats["current_price"] - 1) * 100
    base = feats[~skipped_mask(feats, skip_windows, "trade_date")]
    feats["gap_excess"] = feats["gap"] - feats["trade_date"].map(base.groupby("trade_date")["gap"].mean())

    cols = ["code", "trade_date", "entry_date", "entry_price", "gap_excess", "industry", "scale", "turnover_q",
            *VALUE_COLS]
    df = disc.merge(feats[cols], left_on=["code", "base_date"], right_on=["code", "trade_date"], how="inner"
                    ).drop(columns="trade_date")
    df = df.dropna(subset=["entry_date", "entry_price"])
    df = df[df["entry_price"] > 0]

    df = df.merge(regimes, left_on="base_date", right_on="trade_date", how="left").drop(columns="trade_date")
    ranked_count = industries.dropna(subset=["rank_20d"]).groupby("trade_date")["rank_20d"].count().rename("ranked_count")
    ind = industries.join(ranked_count, on="trade_date")
    ind["industry_trend"] = [industry_trend_of(r, n) for r, n in zip(ind["rank_20d"], ind["ranked_count"])]
    df = df.merge(ind[["trade_date", "industry", "industry_trend"]],
                  left_on=["base_date", "industry"], right_on=["trade_date", "industry"], how="left"
                  ).drop(columns="trade_date")

    now = datetime.now()

    def clean(v, digits=None):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return None
        return round(float(v), digits) if digits is not None else v

    records = []
    for r in df.itertuples(index=False):
        change = float(r.change_pct) if r.change_pct is not None else None
        records.append({
            "disc_no":        r.disc_no,
            "code":           r.code,
            "disc_date":      r.disc_date,
            "event":          f"{r.event_type}_{r.direction}",
            "change_bucket":  change_bucket_of(r.direction, change),
            "change_pct":     clean(change, 2),
            "base_date":      r.base_date,
            "entry_date":     r.entry_date,
            "entry_price":    round(float(r.entry_price), 1),
            "gap_excess":     clean(r.gap_excess, 4),
            **{c: clean(getattr(r, c), 4) for c in VALUE_COLS},
            "industry":       r.industry,
            "scale":          r.scale if isinstance(r.scale, str) else None,
            "turnover_q":     int(r.turnover_q) if not pd.isna(r.turnover_q) else None,
            "industry_trend": r.industry_trend if isinstance(r.industry_trend, str) else None,
            "regime":         r.regime if isinstance(r.regime, str) else None,
            "updated_at":     now,
        })
    log.info("保存: %d 件", len(records))

    with SessionLocal() as db:
        db.execute(text("DELETE FROM trader_schema.disclosure_trades"))
        for i in range(0, len(records), 1000):
            db.execute(pg_insert(DisclosureTrade).values(records[i:i + 1000]))
        db.commit()

    elapsed = (datetime.now() - start).total_seconds()
    log.info("完了: %d 件保存 (%.1f 秒)", len(records), elapsed)
    log.info("=== 開示の取引損益計算バッチ 終了 ===")


if __name__ == "__main__":
    main()
