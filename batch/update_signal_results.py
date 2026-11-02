"""
signal_history のリターン列を埋めるバッチ。

  return_Nd      : シグナル発生日から N 取引日後の株価リターン（%）
  mkt_excess_Nd  : return_Nd − 同日の市場平均リターン（全銘柄の等加重平均）
  ind_excess_Nd  : return_Nd − 同日の同業種平均リターン（業種内 MIN_INDUSTRY_MEMBERS 銘柄以上の場合のみ）

N 取引日 = その銘柄の stock_price に実際に存在する取引日を N 件カウントしたもの。
市場・業種平均の計算からは signal_skip の除外期間（分割・極端な値動き）にある銘柄を除く。

実行方法:
    cd app_works_backend
    .venv\\Scripts\\python batch\\update_signal_results.py
"""

import sys
import os
import logging
from datetime import datetime

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv()

from app.database import SessionLocal
from batch.signal_skip_util import load_skip_windows, skipped_mask

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PERIODS = [3, 5, 10, 20]
MIN_INDUSTRY_MEMBERS = 3
RESULT_COLS = [f"{p}_{n}d" for p in ["return", "mkt_excess", "ind_excess"] for n in PERIODS]


def calc_forward_returns(prices: pd.DataFrame, skip_windows: pd.DataFrame) -> pd.DataFrame:
    """銘柄×日付ごとの N 日後リターンと、市場・業種平均との差を計算する。"""
    prices = prices.sort_values(["code", "trade_date"]).copy()
    g = prices.groupby("code")["current_price"]
    for n in PERIODS:
        prices[f"return_{n}d"] = (g.shift(-n) / prices["current_price"] - 1) * 100

    # 除外期間の銘柄は平均の計算に使わない
    base = prices[~skipped_mask(prices, skip_windows, "trade_date")]
    for n in PERIODS:
        col = f"return_{n}d"
        mkt = base.groupby("trade_date")[col].mean().rename("mkt")
        ind = base.groupby(["trade_date", "industry"])[col].agg(["mean", "count"])
        ind["mean"] = ind["mean"].where(ind["count"] >= MIN_INDUSTRY_MEMBERS)
        prices = prices.join(mkt, on="trade_date").join(ind["mean"].rename("ind"), on=["trade_date", "industry"])
        prices[f"mkt_excess_{n}d"] = prices[col] - prices["mkt"]
        prices[f"ind_excess_{n}d"] = prices[col] - prices["ind"]
        prices = prices.drop(columns=["mkt", "ind"])
    return prices


def main() -> None:
    start = datetime.now()
    log.info("=== シグナル結果更新バッチ 開始 ===")

    null_cond = " OR ".join(f"{c} IS NULL" for c in RESULT_COLS)
    with SessionLocal() as db:
        sig_rows = db.execute(text(f"""
            SELECT id, code, signal_date, price_at_signal, {", ".join(RESULT_COLS)}
            FROM trader_schema.signal_history
            WHERE ({null_cond})
              AND price_at_signal IS NOT NULL
        """)).fetchall()

        if not sig_rows:
            log.info("更新対象なし")
            log.info("=== シグナル結果更新バッチ 終了 ===")
            return

        price_rows = db.execute(text("""
            SELECT sp.code, sm.industry, sp.trade_date, sp.current_price
            FROM trader_schema.stock_price sp
            JOIN trader_schema.stock_master sm ON sp.code = sm.code
            WHERE sp.current_price IS NOT NULL
        """)).fetchall()
        skip_windows = load_skip_windows(db)

    log.info("更新対象: %d 件", len(sig_rows))

    prices = pd.DataFrame(price_rows, columns=["code", "industry", "trade_date", "current_price"])
    prices["current_price"] = prices["current_price"].astype(float)
    fwd = calc_forward_returns(prices, skip_windows).set_index(["code", "trade_date"])

    sigs = pd.DataFrame(sig_rows, columns=["id", "code", "signal_date", "price_at_signal", *RESULT_COLS])
    sigs = sigs.join(fwd[RESULT_COLS], on=["code", "signal_date"], rsuffix="_new")

    params: list[dict] = []
    for row in sigs.itertuples(index=False):
        values = {}
        for c in RESULT_COLS:
            if getattr(row, c) is not None:
                continue  # すでに値あり
            v = getattr(row, f"{c}_new")
            if v is not None and not np.isnan(v):
                values[c] = round(float(v), 4)
        if values:
            params.append({"id": row.id, **{c: values.get(c) for c in RESULT_COLS}})

    if params:
        set_clause = ", ".join(f"{c} = COALESCE({c}, :{c})" for c in RESULT_COLS)
        with SessionLocal() as db:
            db.execute(text(f"UPDATE trader_schema.signal_history SET {set_clause} WHERE id = :id"), params)
            db.commit()

    elapsed = (datetime.now() - start).total_seconds()
    log.info("完了: %d 件更新 (%.1f 秒)", len(params), elapsed)
    log.info("=== シグナル結果更新バッチ 終了 ===")


if __name__ == "__main__":
    main()
