"""
市場全体の地合い（market_breadth）と業種別の強弱（industry_daily）を計算し、保存するバッチ。

market_breadth（取引日ごと）
  adv_count / dec_count : 前日比で上昇・下落した銘柄数
  adv_dec_ratio_25      : 騰落レシオ（直近25取引日の上昇銘柄数合計 ÷ 下落銘柄数合計 × 100）
  pct_above_ma25        : 終値が25日移動平均より上にある銘柄の割合（%）
  avg_rsi14             : 全銘柄の RSI14 の平均
  mkt_return / mkt_index: 全銘柄の等加重平均リターン（%）と、それを積み上げた指数（初日 = 100）
  regime                : pct_above_ma25 による地合いの区分（strong: 60%以上 / neutral / weak: 40%以下）

industry_daily（取引日 × 33業種）
  return_1d / index_value       : 業種内の等加重平均リターン（%）と、それを積み上げた業種指数（初日 = 100）
  return_5d / return_20d        : 業種指数の過去 5 / 20 取引日リターン（%）
  excess_5d / excess_20d        : 同期間の市場指数リターンとの差（%）
  rank_5d / rank_20d            : excess の大きい順の順位（1 = 最も強い）。構成銘柄が MIN_MEMBERS 未満の業種は順位なし
  pct_above_ma25                : 業種内で終値が25日移動平均より上にある銘柄の割合（%）

signal_skip の除外期間（分割・極端な値動き）にある銘柄は、すべての集計から除く。
毎回全期間を計算し直して upsert する（冪等）。

実行方法:
    cd app_works_backend
    .venv\\Scripts\\python batch\\calc_market_context.py
"""

import sys
import os
import logging
from datetime import datetime
from decimal import Decimal

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv()

from app.database import SessionLocal
from app.models.industry_daily import IndustryDaily
from app.models.market_breadth import MarketBreadth
from batch.signal_skip_util import load_skip_windows, skipped_mask

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ADR_DAYS = 25            # 騰落レシオの集計日数
MIN_MEMBERS = 3          # 業種の順位付けに必要な構成銘柄数
REGIME_STRONG = 60.0     # pct_above_ma25 がこれ以上なら強い地合い
REGIME_WEAK = 40.0       # pct_above_ma25 がこれ以下なら弱い地合い


def regime_of(pct_above_ma25: float | None) -> str | None:
    if pct_above_ma25 is None or np.isnan(pct_above_ma25):
        return None
    if pct_above_ma25 >= REGIME_STRONG:
        return "strong"
    if pct_above_ma25 <= REGIME_WEAK:
        return "weak"
    return "neutral"


def load_prices(db) -> pd.DataFrame:
    """銘柄×日付の終値・前日比・MA25・RSI14 を返す（除外期間の行は除いたもの）。"""
    rows = db.execute(text("""
        SELECT sp.code, sm.industry, sp.trade_date, sp.current_price, ti.ma25, ti.rsi14
        FROM trader_schema.stock_price sp
        JOIN trader_schema.stock_master sm ON sp.code = sm.code
        LEFT JOIN trader_schema.technical_indicators ti
               ON ti.code = sp.code AND ti.trade_date = sp.trade_date
        WHERE sp.current_price IS NOT NULL
    """)).fetchall()
    skip_windows = load_skip_windows(db)

    df = pd.DataFrame(rows, columns=["code", "industry", "trade_date", "current_price", "ma25", "rsi14"])
    for col in ["current_price", "ma25", "rsi14"]:
        df[col] = df[col].astype(float)
    df = df.sort_values(["code", "trade_date"])
    df["ret"] = (df["current_price"] / df.groupby("code")["current_price"].shift(1) - 1) * 100
    df["above"] = np.where(df["ma25"].isna(), np.nan, (df["current_price"] > df["ma25"]).astype(float))

    skipped = skipped_mask(df, skip_windows, "trade_date")
    log.info("株価データ: %d 行（除外期間のため %d 行を除外）", int((~skipped).sum()), int(skipped.sum()))
    return df[~skipped]


def calc_breadth(df: pd.DataFrame) -> pd.DataFrame:
    """取引日ごとの地合い指標を計算する。"""
    g = df.groupby("trade_date")
    b = pd.DataFrame({
        "stock_count":    g["code"].count(),
        "adv_count":      g["ret"].apply(lambda s: int((s > 0).sum())),
        "dec_count":      g["ret"].apply(lambda s: int((s < 0).sum())),
        "pct_above_ma25": g["above"].mean() * 100,
        "avg_rsi14":      g["rsi14"].mean(),
        "mkt_return":     g["ret"].mean(),
    }).sort_index()

    adv_sum = b["adv_count"].rolling(ADR_DAYS).sum()
    dec_sum = b["dec_count"].rolling(ADR_DAYS).sum()
    b["adv_dec_ratio_25"] = adv_sum / dec_sum.replace(0, np.nan) * 100
    b["mkt_index"] = 100 * (1 + b["mkt_return"].fillna(0) / 100).cumprod()
    b["regime"] = b["pct_above_ma25"].map(regime_of)
    return b


def calc_industry(df: pd.DataFrame, breadth: pd.DataFrame) -> pd.DataFrame:
    """取引日 × 業種ごとの強弱を計算する。"""
    g = df.groupby(["industry", "trade_date"])
    ind = pd.DataFrame({
        "member_count":   g["code"].count(),
        "return_1d":      g["ret"].mean(),
        "pct_above_ma25": g["above"].mean() * 100,
    }).reset_index().sort_values(["industry", "trade_date"])

    ind["index_value"] = ind.groupby("industry")["return_1d"].transform(
        lambda s: 100 * (1 + s.fillna(0) / 100).cumprod()
    )
    mkt_index = breadth["mkt_index"]
    for n in [5, 20]:
        ind[f"return_{n}d"] = (ind["index_value"] / ind.groupby("industry")["index_value"].shift(n) - 1) * 100
        mkt_ret = (mkt_index / mkt_index.shift(n) - 1) * 100
        ind[f"excess_{n}d"] = ind[f"return_{n}d"] - ind["trade_date"].map(mkt_ret)
        rankable = ind[f"excess_{n}d"].where(ind["member_count"] >= MIN_MEMBERS)
        ind[f"rank_{n}d"] = rankable.groupby(ind["trade_date"]).rank(ascending=False, method="min")
    return ind


def dec(v, digits: int) -> Decimal | None:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return Decimal(str(round(float(v), digits)))


def to_int(v) -> int | None:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return int(v)


def main() -> None:
    start = datetime.now()
    log.info("=== 地合い・業種強弱計算バッチ 開始 ===")

    with SessionLocal() as db:
        df = load_prices(db)
    if df.empty:
        log.info("株価データなし")
        log.info("=== 地合い・業種強弱計算バッチ 終了 ===")
        return

    breadth = calc_breadth(df)
    ind = calc_industry(df, breadth)
    now = datetime.now()

    breadth_records = [
        {
            "trade_date":       d,
            "stock_count":      int(r.stock_count),
            "adv_count":        int(r.adv_count),
            "dec_count":        int(r.dec_count),
            "adv_dec_ratio_25": dec(r.adv_dec_ratio_25, 2),
            "pct_above_ma25":   dec(r.pct_above_ma25, 2),
            "avg_rsi14":        dec(r.avg_rsi14, 2),
            "mkt_return":       dec(r.mkt_return, 4),
            "mkt_index":        dec(r.mkt_index, 4),
            "regime":           r.regime,
            "updated_at":       now,
        }
        for d, r in breadth.iterrows()
    ]
    ind_records = [
        {
            "trade_date":     r.trade_date,
            "industry":       r.industry,
            "member_count":   int(r.member_count),
            "return_1d":      dec(r.return_1d, 4),
            "index_value":    dec(r.index_value, 4),
            "return_5d":      dec(r.return_5d, 4),
            "return_20d":     dec(r.return_20d, 4),
            "excess_5d":      dec(r.excess_5d, 4),
            "excess_20d":     dec(r.excess_20d, 4),
            "rank_5d":        to_int(r.rank_5d),
            "rank_20d":       to_int(r.rank_20d),
            "pct_above_ma25": dec(r.pct_above_ma25, 2),
            "updated_at":     now,
        }
        for r in ind.itertuples(index=False)
    ]

    log.info("保存: market_breadth %d 件 / industry_daily %d 件", len(breadth_records), len(ind_records))
    with SessionLocal() as db:
        for model, records, constraint in [
            (MarketBreadth, breadth_records, None),
            (IndustryDaily, ind_records, "uq_industry_daily_date_industry"),
        ]:
            update_cols = [c for c in records[0] if c not in ("trade_date", "industry")]
            for i in range(0, len(records), 1000):
                stmt = pg_insert(model).values(records[i:i + 1000])
                conflict = {"constraint": constraint} if constraint else {"index_elements": ["trade_date"]}
                stmt = stmt.on_conflict_do_update(**conflict, set_={c: stmt.excluded[c] for c in update_cols})
                db.execute(stmt)
        db.commit()

    latest = breadth.iloc[-1]
    log.info(
        "最新 %s: 地合い=%s 25日線上%.1f%% 騰落レシオ%.1f",
        breadth.index[-1], latest.regime, latest.pct_above_ma25, latest.adv_dec_ratio_25,
    )
    elapsed = (datetime.now() - start).total_seconds()
    log.info("完了 (%.1f 秒)", elapsed)
    log.info("=== 地合い・業種強弱計算バッチ 終了 ===")


if __name__ == "__main__":
    main()
