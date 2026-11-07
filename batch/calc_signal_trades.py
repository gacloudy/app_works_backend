"""
シグナル1回ごとに「翌取引日の始値で買い、N 取引日後の終値で売った」場合の損益と、そのときの状況を
signal_trades に保存するバッチ。update_signal_results と calc_market_context の後に実行する。

  ret_Nd        : (シグナル日から N 取引日後の終値 / 翌取引日の始値 − 1) × 100（手数料前）
                  N 取引日 = その銘柄の stock_price に実際にある取引日を数えたもの（update_signal_results と同じ）
  excess_Nd     : ret_Nd − 同じシグナル日に全銘柄で同じ売買をした場合の平均（除外期間の銘柄を除く）
  lift_X_Nd     : ret_Nd − 同じシグナル日に同じ区分にいた全銘柄の平均（X = ind: 業種 / scale: 規模区分 /
                  turn: 売買代金の5分位 / vol: 出来高比率）。区分そのものの強弱を除いた、シグナルの上乗せ分
  turnover_20d  : シグナル日までの20取引日の平均売買代金（出来高 × 終値、円）
  turnover_q    : 同じ日の全銘柄の中での turnover_20d の5分位（1 = 小さい 〜 5 = 大きい）
  volume_bucket : シグナル当日の出来高比率（technical_indicators.volume_ratio）を <1x / 1-2x / 2-3x / 3x+ に分けたもの
  scale         : TOPIX規模区分（stock_master の現在の区分。過去時点の区分ではない）
  industry_trend: シグナル日の業種の過去20日の強さ（aggregate_context_stats と同じ3分割）
  regime        : シグナル日の地合い（market_breadth.regime）
  recent_disclosure : シグナル日以前 30 日以内の直近の決算・修正（"earn_revision_up" など。なければ "none"、
                      決算データの取得範囲外は NULL）

毎回全件を作り直す（冪等）。

実行方法:
    cd app_works_backend
    .venv\\Scripts\\python batch\\calc_signal_trades.py
"""

import sys
import os
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
from app.models.signal_trade import SignalTrade
from batch.aggregate_context_stats import industry_trend_of
from batch.signal_skip_util import load_skip_windows, skipped_mask

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PERIODS = [5, 10, 20]
TURNOVER_DAYS = 20
TURNOVER_BUCKETS = 5
# 上乗せ（lift）の比較相手: 同じ日に同じ区分にいた全銘柄の平均
LIFT_KEYS = {"ind": "industry", "scale": "scale", "turn": "turnover_q", "vol": "volume_bucket"}
LIFT_COLS = [f"lift_{name}_{n}d" for name in LIFT_KEYS for n in PERIODS]
RECENT_DISCLOSURE_DAYS = 30  # シグナル日から何日前までの決算・修正を「直近」とみなすか（暦日）


def volume_bucket_of(ratio: float) -> str | None:
    if ratio is None or np.isnan(ratio):
        return None
    if ratio < 1:
        return "<1x"
    if ratio < 2:
        return "1-2x"
    if ratio < 3:
        return "2-3x"
    return "3x+"


def calc_price_features(prices: pd.DataFrame, skip_windows: pd.DataFrame) -> pd.DataFrame:
    """銘柄×日付ごとに、翌日始値で買った場合の N 日後の損益・市場平均との差・売買代金を計算する。"""
    p = prices.sort_values(["code", "trade_date"]).copy()
    g = p.groupby("code")
    p["entry_date"] = g["trade_date"].shift(-1)
    p["entry_price"] = g["open_price"].shift(-1)
    for n in PERIODS:
        p[f"ret_{n}d"] = (g["current_price"].shift(-n) / p["entry_price"] - 1) * 100

    p["turnover"] = p["volume"] * p["current_price"]
    p["turnover_20d"] = g["turnover"].transform(lambda s: s.rolling(TURNOVER_DAYS, min_periods=TURNOVER_DAYS).mean())
    pct = p.groupby("trade_date")["turnover_20d"].rank(pct=True)
    p["turnover_q"] = np.ceil(pct * TURNOVER_BUCKETS).clip(1, TURNOVER_BUCKETS)

    p["volume_bucket"] = p["volume_ratio"].map(volume_bucket_of)

    # 市場平均（同じ日に全銘柄で同じ売買をした場合）。除外期間の銘柄は平均に使わない
    base = p[~skipped_mask(p, skip_windows, "trade_date")]
    for n in PERIODS:
        col = f"ret_{n}d"
        mkt = base.groupby("trade_date")[col].mean()
        p[f"excess_{n}d"] = p[col] - p["trade_date"].map(mkt)
        # 同じ日・同じ区分の全銘柄の平均との差（区分そのものの強弱を除いた、シグナルの上乗せ分）
        for name, key in LIFT_KEYS.items():
            seg_mean = base.groupby(["trade_date", key])[col].mean().rename("seg_mean")
            p = p.join(seg_mean, on=["trade_date", key])
            p[f"lift_{name}_{n}d"] = p[col] - p["seg_mean"]
            p = p.drop(columns="seg_mean")
    return p


def load_prices(db) -> pd.DataFrame:
    """銘柄×日付の始値・終値・出来高と、業種・規模区分・出来高比率を返す。"""
    prices = pd.read_sql(text("""
        SELECT sp.code, sp.trade_date, sp.open_price, sp.current_price, sp.volume,
               sm.industry, sm.scale, ti.volume_ratio
        FROM trader_schema.stock_price sp
        JOIN trader_schema.stock_master sm ON sm.code = sp.code
        LEFT JOIN trader_schema.technical_indicators ti
               ON ti.code = sp.code AND ti.trade_date = sp.trade_date
        WHERE sp.current_price IS NOT NULL
    """), db.connection())
    for c in ["open_price", "current_price", "volume", "volume_ratio"]:
        prices[c] = prices[c].astype(float)
    return prices


def recent_disclosure_of(signals: pd.DataFrame, disclosures: pd.DataFrame) -> list[str | None]:
    """各シグナルについて、シグナル日以前 RECENT_DISCLOSURE_DAYS 日以内の直近の決算・修正を返す。

    該当がなければ "none"。決算データの取得範囲外（最後の開示日より後）のシグナルは、
    開示があったか分からないため None にする。
    """
    if disclosures.empty:
        return [None] * len(signals)
    disc = disclosures.copy()
    disc["disc_date"] = pd.to_datetime(disc["disc_date"])
    disc = disc.sort_values("disc_date")
    last_disc = disc["disc_date"].max()

    sig = signals[["code", "signal_date"]].copy()
    sig["_order"] = range(len(sig))
    sig["signal_ts"] = pd.to_datetime(sig["signal_date"])
    merged = pd.merge_asof(
        sig.sort_values("signal_ts"), disc, left_on="signal_ts", right_on="disc_date", by="code",
        direction="backward", tolerance=pd.Timedelta(days=RECENT_DISCLOSURE_DAYS),
    ).sort_values("_order")
    result = merged["event"].where(merged["event"].notna(), "none")
    result = result.where(merged["signal_ts"] <= last_disc, None)
    return list(result)


def main() -> None:
    start = datetime.now()
    log.info("=== シグナル取引損益計算バッチ 開始 ===")

    with SessionLocal() as db:
        signals = pd.read_sql(text("""
            SELECT sh.code, sh.signal_date, sh.signal_type, sm.industry, sm.scale, ti.volume_ratio
            FROM trader_schema.signal_history sh
            JOIN trader_schema.stock_master sm ON sm.code = sh.code
            LEFT JOIN trader_schema.technical_indicators ti
                   ON ti.code = sh.code AND ti.trade_date = sh.signal_date
        """), db.connection())
        prices = load_prices(db)
        disclosures = pd.read_sql(text("""
            SELECT code, disc_date, event_type || '_' || direction AS event
            FROM trader_schema.fin_disclosure
            WHERE direction IS NOT NULL
        """), db.connection())
        regimes = pd.read_sql(text("SELECT trade_date, regime FROM trader_schema.market_breadth"), db.connection())
        industries = pd.read_sql(text("SELECT trade_date, industry, rank_20d FROM trader_schema.industry_daily"),
                                 db.connection())
        skip_windows = load_skip_windows(db)

    if signals.empty:
        log.info("シグナルなし")
        log.info("=== シグナル取引損益計算バッチ 終了 ===")
        return
    log.info("シグナル: %d 件 / 株価: %d 行", len(signals), len(prices))

    feats = calc_price_features(prices, skip_windows)
    feat_cols = ["entry_date", "entry_price", "turnover_20d", "turnover_q",
                 *[f"{p}_{n}d" for p in ["ret", "excess"] for n in PERIODS], *LIFT_COLS]
    df = signals.merge(
        feats[["code", "trade_date", *feat_cols]],
        left_on=["code", "signal_date"], right_on=["code", "trade_date"], how="left",
    ).drop(columns="trade_date")

    # 翌取引日の始値がない（直近のシグナル、始値の欠損）ものは売買できないので除く
    df = df.dropna(subset=["entry_date", "entry_price"])
    df = df[df["entry_price"] > 0]

    df["volume_ratio"] = df["volume_ratio"].astype(float)
    df["volume_bucket"] = df["volume_ratio"].map(volume_bucket_of)
    df = df.merge(regimes, left_on="signal_date", right_on="trade_date", how="left").drop(columns="trade_date")
    ranked = industries.dropna(subset=["rank_20d"])
    ranked_count = ranked.groupby("trade_date")["rank_20d"].count().rename("ranked_count")
    ind = industries.join(ranked_count, on="trade_date")
    ind["industry_trend"] = [industry_trend_of(r, n) for r, n in zip(ind["rank_20d"], ind["ranked_count"])]
    df = df.merge(ind[["trade_date", "industry", "industry_trend"]],
                  left_on=["signal_date", "industry"], right_on=["trade_date", "industry"], how="left"
                  ).drop(columns="trade_date")
    df["recent_disclosure"] = recent_disclosure_of(df, disclosures)

    now = datetime.now()

    def clean(v, digits=None):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return None
        if digits is not None:
            return round(float(v), digits)
        return v

    records = [
        {
            "code":           r.code,
            "signal_date":    r.signal_date,
            "signal_type":    r.signal_type,
            "entry_date":     r.entry_date,
            "entry_price":    round(float(r.entry_price), 1),
            **{f"{p}_{n}d": clean(getattr(r, f"{p}_{n}d"), 4) for p in ["ret", "excess"] for n in PERIODS},
            **{c: clean(getattr(r, c), 4) for c in LIFT_COLS},
            "industry":       r.industry,
            "scale":          r.scale,
            "turnover_20d":   clean(r.turnover_20d, 0),
            "turnover_q":     int(r.turnover_q) if not pd.isna(r.turnover_q) else None,
            "volume_ratio":   clean(r.volume_ratio, 4),
            "volume_bucket":  r.volume_bucket,
            "industry_trend": r.industry_trend if isinstance(r.industry_trend, str) else None,
            "regime":         r.regime if isinstance(r.regime, str) else None,
            "recent_disclosure": r.recent_disclosure if isinstance(r.recent_disclosure, str) else None,
            "updated_at":     now,
        }
        for r in df.itertuples(index=False)
    ]
    log.info("保存: %d 件", len(records))

    with SessionLocal() as db:
        db.execute(text("DELETE FROM trader_schema.signal_trades"))
        for i in range(0, len(records), 1000):
            db.execute(pg_insert(SignalTrade).values(records[i:i + 1000]))
        db.commit()

    elapsed = (datetime.now() - start).total_seconds()
    log.info("完了: %d 件保存 (%.1f 秒)", len(records), elapsed)
    log.info("=== シグナル取引損益計算バッチ 終了 ===")


if __name__ == "__main__":
    main()
