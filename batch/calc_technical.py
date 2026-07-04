"""
株価テクニカル指標を計算し、technical_indicators テーブルに保存するバッチ。

計算指標: MA5/25/75, MACD(12/26/9), RSI(14), ボリンジャーバンド(20,±2σ), 出来高比率

実行方法:
    cd app_works_backend
    .venv\\Scripts\\python batch\\calc_technical.py
"""

import sys
import os
import logging
from datetime import datetime, timedelta
from decimal import Decimal

import pandas as pd
import numpy as np
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv()

from app.database import SessionLocal
from app.models.technical_indicator import TechnicalIndicator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

WARMUP_DAYS = 150  # MA75のためのカレンダー日数バッファ（約75取引日分）


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).round(2)


def calc_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """1銘柄分のDataFrame（trade_date, current_price, volume）に指標カラムを追加して返す。"""
    df = df.sort_values("trade_date").copy()
    close = df["current_price"].astype(float)
    volume = df["volume"].fillna(0).astype(float)

    df["ma5"]  = close.rolling(5).mean().round(2)
    df["ma25"] = close.rolling(25).mean().round(2)
    df["ma75"] = close.rolling(75).mean().round(2)

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    df["macd"]        = macd_line.round(4)
    df["macd_signal"] = signal_line.round(4)
    df["macd_hist"]   = (macd_line - signal_line).round(4)

    df["rsi14"] = calc_rsi(close, 14)

    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    df["bb_upper"]  = (bb_mid + 2 * bb_std).round(2)
    df["bb_middle"] = bb_mid.round(2)
    df["bb_lower"]  = (bb_mid - 2 * bb_std).round(2)

    vol_ma20 = volume.rolling(20).mean()
    df["volume_ma20"]  = vol_ma20.round(2)
    df["volume_ratio"] = (volume / vol_ma20.replace(0, np.nan)).round(4)

    return df


def to_dec(v) -> Decimal | None:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


def main() -> None:
    start = datetime.now()
    log.info("=== テクニカル指標計算バッチ 開始 ===")

    with SessionLocal() as db:
        last_date = db.execute(
            text("SELECT MAX(trade_date) FROM trader_schema.technical_indicators")
        ).scalar()

    if last_date:
        fetch_from = last_date - timedelta(days=WARMUP_DAYS)
        log.info("前回最終日: %s → %s 以降のデータを取得", last_date, fetch_from)
    else:
        fetch_from = None
        log.info("初回実行: 全データを取得")

    with SessionLocal() as db:
        q = """
            SELECT sp.code, sp.trade_date, sp.current_price, sp.volume
            FROM trader_schema.stock_price sp
            JOIN trader_schema.stock_master sm ON sp.code = sm.code
            WHERE sp.current_price IS NOT NULL
        """
        params: dict = {}
        if fetch_from:
            q += " AND sp.trade_date >= :fetch_from"
            params["fetch_from"] = fetch_from
        q += " ORDER BY sp.code, sp.trade_date"
        rows = db.execute(text(q), params).fetchall()

    if not rows:
        log.info("処理対象データなし")
        return

    df_all = pd.DataFrame(rows, columns=["code", "trade_date", "current_price", "volume"])
    codes = df_all["code"].unique()
    log.info("対象銘柄: %d 件、対象行: %d 行", len(codes), len(df_all))

    records: list[dict] = []
    for code in codes:
        df_stock = df_all[df_all["code"] == code]
        if len(df_stock) < 5:
            continue
        df_ind = calc_indicators(df_stock)
        if last_date is not None:
            df_ind = df_ind[df_ind["trade_date"] > last_date]
        if df_ind.empty:
            continue
        for _, row in df_ind.iterrows():
            records.append({
                "code":         code,
                "trade_date":   row["trade_date"],
                "ma5":          to_dec(row.get("ma5")),
                "ma25":         to_dec(row.get("ma25")),
                "ma75":         to_dec(row.get("ma75")),
                "macd":         to_dec(row.get("macd")),
                "macd_signal":  to_dec(row.get("macd_signal")),
                "macd_hist":    to_dec(row.get("macd_hist")),
                "rsi14":        to_dec(row.get("rsi14")),
                "bb_upper":     to_dec(row.get("bb_upper")),
                "bb_middle":    to_dec(row.get("bb_middle")),
                "bb_lower":     to_dec(row.get("bb_lower")),
                "volume_ma20":  to_dec(row.get("volume_ma20")),
                "volume_ratio": to_dec(row.get("volume_ratio")),
                "created_at":   datetime.now(),
            })

    log.info("指標計算完了: %d 件 → DB保存中...", len(records))

    CHUNK = 500
    with SessionLocal() as db:
        for i in range(0, len(records), CHUNK):
            chunk = records[i:i + CHUNK]
            stmt = pg_insert(TechnicalIndicator).values(chunk)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_tech_code_date",
                set_={c: stmt.excluded[c] for c in [
                    "ma5", "ma25", "ma75", "macd", "macd_signal", "macd_hist",
                    "rsi14", "bb_upper", "bb_middle", "bb_lower", "volume_ma20", "volume_ratio",
                ]},
            )
            db.execute(stmt)
        db.commit()

    elapsed = (datetime.now() - start).total_seconds()
    log.info("完了: %d 件保存 (%.1f 秒)", len(records), elapsed)
    log.info("=== テクニカル指標計算バッチ 終了 ===")


if __name__ == "__main__":
    main()
