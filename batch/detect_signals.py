"""
technical_indicators テーブルからシグナルを検出し、signal_history に保存するバッチ。

検出シグナル:
  golden_cross     : MA5 が MA25 を上抜け（買いシグナル）
  dead_cross       : MA5 が MA25 を下抜け（売りシグナル）
  rsi_oversold     : RSI14 が 30 以下に突入（売られすぎ）
  rsi_overbought   : RSI14 が 70 以上に突入（買われすぎ）
  bb_lower_touch   : 株価がボリンジャー下限に触れた
  bb_upper_touch   : 株価がボリンジャー上限に触れた
  volume_surge_up  : 出来高が20日平均の2倍超 かつ 上昇

実行方法:
    cd app_works_backend
    .venv\\Scripts\\python batch\\detect_signals.py
"""

import sys
import os
import json
import logging
from datetime import datetime
from decimal import Decimal

import pandas as pd
import numpy as np
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv()

from app.database import SessionLocal
from app.models.signal_history import SignalHistory

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

RSI_OVERSOLD  = 30.0
RSI_OVERBOUGHT = 70.0
VOLUME_SURGE_RATIO = 2.0


def detect_for_stock(code: str, df: pd.DataFrame, price_df: pd.DataFrame) -> list[dict]:
    """1銘柄分のシグナルを検出して dict のリストで返す。"""
    if len(df) < 2:
        return []

    df = df.sort_values("trade_date").reset_index(drop=True)
    signals: list[dict] = []

    for i in range(1, len(df)):
        prev = df.iloc[i - 1]
        curr = df.iloc[i]
        sig_date = curr["trade_date"]

        def _price_at(d):
            rows = price_df[(price_df["code"] == code) & (price_df["trade_date"] == d)]
            if rows.empty:
                return None
            v = rows.iloc[0]["current_price"]
            return float(v) if v is not None else None

        def _add(stype: str, detail_dict: dict):
            signals.append({
                "code":            code,
                "signal_date":     sig_date,
                "signal_type":     stype,
                "detail":          json.dumps(detail_dict, ensure_ascii=False),
                "price_at_signal": Decimal(str(round(p, 1))) if (p := _price_at(sig_date)) else None,
                "return_3d":       None,
                "return_5d":       None,
                "return_10d":      None,
                "return_20d":      None,
                "created_at":      datetime.now(),
            })

        def _v(row, col):
            v = row.get(col)
            if v is None or (isinstance(v, float) and np.isnan(v)):
                return None
            return float(v)

        # ゴールデンクロス / デッドクロス
        p_ma5, p_ma25 = _v(prev, "ma5"), _v(prev, "ma25")
        c_ma5, c_ma25 = _v(curr, "ma5"), _v(curr, "ma25")
        if all(v is not None for v in [p_ma5, p_ma25, c_ma5, c_ma25]):
            if p_ma5 < p_ma25 and c_ma5 >= c_ma25:
                _add("golden_cross", {"ma5": round(c_ma5, 2), "ma25": round(c_ma25, 2)})
            elif p_ma5 > p_ma25 and c_ma5 <= c_ma25:
                _add("dead_cross", {"ma5": round(c_ma5, 2), "ma25": round(c_ma25, 2)})

        # RSI 売られすぎ / 買われすぎ
        p_rsi, c_rsi = _v(prev, "rsi14"), _v(curr, "rsi14")
        if p_rsi is not None and c_rsi is not None:
            if p_rsi > RSI_OVERSOLD and c_rsi <= RSI_OVERSOLD:
                _add("rsi_oversold", {"rsi14": round(c_rsi, 2), "prev_rsi14": round(p_rsi, 2)})
            elif p_rsi < RSI_OVERBOUGHT and c_rsi >= RSI_OVERBOUGHT:
                _add("rsi_overbought", {"rsi14": round(c_rsi, 2), "prev_rsi14": round(p_rsi, 2)})

        # ボリンジャーバンド タッチ
        price = _price_at(sig_date)
        if price is not None:
            p_bbl, c_bbl = _v(prev, "bb_lower"), _v(curr, "bb_lower")
            p_bbu, c_bbu = _v(prev, "bb_upper"), _v(curr, "bb_upper")
            p_price_rows = price_df[(price_df["code"] == code) & (price_df["trade_date"] == prev["trade_date"])]
            p_price = float(p_price_rows.iloc[0]["current_price"]) if not p_price_rows.empty else None

            if p_price is not None and p_bbl is not None and c_bbl is not None:
                if p_price > p_bbl and price <= c_bbl:
                    _add("bb_lower_touch", {"price": round(price, 1), "bb_lower": round(c_bbl, 2)})
            if p_price is not None and p_bbu is not None and c_bbu is not None:
                if p_price < p_bbu and price >= c_bbu:
                    _add("bb_upper_touch", {"price": round(price, 1), "bb_upper": round(c_bbu, 2)})

        # 出来高急増 + 上昇
        vol_ratio = _v(curr, "volume_ratio")
        if vol_ratio is not None and vol_ratio >= VOLUME_SURGE_RATIO and price is not None:
            p_price_rows = price_df[(price_df["code"] == code) & (price_df["trade_date"] == prev["trade_date"])]
            if not p_price_rows.empty:
                prev_close = p_price_rows.iloc[0].get("current_price")
                if prev_close is not None and price > float(prev_close):
                    _add("volume_surge_up", {"volume_ratio": round(vol_ratio, 2), "price": round(price, 1)})

    return signals


def main() -> None:
    start = datetime.now()
    log.info("=== シグナル検出バッチ 開始 ===")

    with SessionLocal() as db:
        last_signal_date = db.execute(
            text("SELECT MAX(signal_date) FROM trader_schema.signal_history")
        ).scalar()

    if last_signal_date:
        log.info("前回最終シグナル日: %s → 以降を処理", last_signal_date)
    else:
        log.info("初回実行: 全期間を処理")

    # technical_indicators を取得（前日データも必要なため1日前から）
    with SessionLocal() as db:
        q = """
            SELECT ti.code, ti.trade_date, ti.ma5, ti.ma25, ti.ma75,
                   ti.rsi14, ti.bb_upper, ti.bb_lower, ti.volume_ratio
            FROM trader_schema.technical_indicators ti
            JOIN trader_schema.stock_master sm ON ti.code = sm.code
            WHERE sm."isDelisted" = false
        """
        params: dict = {}
        if last_signal_date:
            # 前日分も必要なため1件前から取得
            q += " AND ti.trade_date >= (SELECT MAX(trade_date) FROM trader_schema.technical_indicators WHERE trade_date < :last_sd)"
            params["last_sd"] = last_signal_date
        q += " ORDER BY ti.code, ti.trade_date"
        ti_rows = db.execute(text(q), params).fetchall()

        # 株価も取得（price_at_signal と前日終値比較用）
        sp_rows = db.execute(text("""
            SELECT code, trade_date, current_price
            FROM trader_schema.stock_price
            WHERE current_price IS NOT NULL
        """)).fetchall()

    if not ti_rows:
        log.info("処理対象データなし")
        return

    df_ti = pd.DataFrame(ti_rows, columns=[
        "code", "trade_date", "ma5", "ma25", "ma75", "rsi14", "bb_upper", "bb_lower", "volume_ratio"
    ])
    df_price = pd.DataFrame(sp_rows, columns=["code", "trade_date", "current_price"])

    # last_signal_date より後の日付のみ対象
    if last_signal_date:
        target_dates = set(df_ti[df_ti["trade_date"] > last_signal_date]["trade_date"].unique())
    else:
        target_dates = set(df_ti["trade_date"].unique())

    codes = df_ti["code"].unique()
    log.info("対象銘柄: %d 件、対象日付: %d 日", len(codes), len(target_dates))

    all_signals: list[dict] = []
    for code in codes:
        df_code = df_ti[df_ti["code"] == code]
        df_p_code = df_price[df_price["code"] == code]
        sigs = detect_for_stock(code, df_code, df_p_code)
        # last_signal_date より後のシグナルのみ
        if last_signal_date:
            sigs = [s for s in sigs if s["signal_date"] > last_signal_date]
        all_signals.extend(sigs)

    log.info("検出シグナル: %d 件 → DB保存中...", len(all_signals))

    if not all_signals:
        log.info("新規シグナルなし")
        log.info("=== シグナル検出バッチ 終了 ===")
        return

    CHUNK = 500
    inserted = 0
    with SessionLocal() as db:
        for i in range(0, len(all_signals), CHUNK):
            chunk = all_signals[i:i + CHUNK]
            stmt = pg_insert(SignalHistory).values(chunk)
            stmt = stmt.on_conflict_do_nothing(constraint="uq_signal_code_date_type")
            result = db.execute(stmt)
            inserted += result.rowcount
        db.commit()

    elapsed = (datetime.now() - start).total_seconds()
    log.info("完了: %d 件挿入 (%.1f 秒)", inserted, elapsed)
    log.info("=== シグナル検出バッチ 終了 ===")


if __name__ == "__main__":
    main()
