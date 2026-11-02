"""
株式分割・データ異常・極端な値動きを検出し、signal_skip テーブルに保存するバッチ。

ここで登録された銘柄・期間は、シグナル検出（detect_signals）、
リターン/超過リターン算出の市場平均（update_signal_results）、
統計集計（aggregate_stats）の対象から除外される。

検出ルール（保存済み前日終値 = stock_price の直前取引日の current_price）:
  split_suspected : 取得元の前日終値 ÷ 保存済み前日終値 が 1.5, 2, 3, 5, 10 倍などの分割比率に近い
                    または 終値が保存済み前日終値の 1/2, 2倍 などの水準に不連続にジャンプした
  price_mismatch  : 取得元の前日終値と保存済み前日終値が 3% 超ずれている（分割比率ではない）
  extreme_move    : 保存済み前日終値からの騰落率の絶対値が 30% 以上

除外期間: 発生日の SKIP_BEFORE_DAYS 日前 〜 SKIP_AFTER_DAYS 日後（暦日）
  前側 … 発生日をまたぐ 20 取引日後リターンが歪むため
  後側 … MA25 / BB20 / RSI14 などの指標が発生日のデータを含む間は歪むため

毎回全期間を走査し、(code, event_date, reason) で upsert する（冪等）。

実行方法:
    cd app_works_backend
    .venv\\Scripts\\python batch\\detect_price_anomalies.py
"""

import sys
import os
import logging
from datetime import datetime, timedelta
from decimal import Decimal

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv()

from app.database import SessionLocal
from app.models.signal_skip import SignalSkip

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PREV_CLOSE_TOLERANCE = 0.03   # 前日終値の不一致とみなすずれ（3%）
SPLIT_RATIO_TOLERANCE = 0.02  # 分割比率（0.5刻み）からのずれの許容（2%）
MIN_SPLIT_RATIO = 1.4         # これ未満の比率は分割とみなさない
CLOSE_JUMP_RATIO = 1.6        # 終値がこの倍率以上/1/倍率以下に飛んだら分割比率を確認する
EXTREME_MOVE_PCT = 30.0       # 極端な値動きとみなす騰落率（%）
SKIP_BEFORE_DAYS = 30
SKIP_AFTER_DAYS = 40


def split_ratio(r: float) -> float | None:
    """r（またはその逆数）が 1.5, 2, 2.5, 3 ... の分割比率に近ければその比率を返す。"""
    if r <= 0:
        return None
    big = r if r >= 1 else 1 / r
    if big < MIN_SPLIT_RATIO:
        return None
    nearest = round(big * 2) / 2
    if abs(big - nearest) / nearest <= SPLIT_RATIO_TOLERANCE:
        return nearest
    return None


def fmt_ratio(r: float, nearest: float) -> str:
    return f"{nearest:g}倍" if r >= 1 else f"1/{nearest:g}"


def detect(df: pd.DataFrame) -> list[dict]:
    """全銘柄の株価 DataFrame（code, trade_date, prev_close, current_price）から異常を検出する。"""
    df = df.sort_values(["code", "trade_date"]).copy()
    g = df.groupby("code")
    df["stored_prev"] = g["current_price"].shift(1)
    df["stored_prev_date"] = g["trade_date"].shift(1)
    df = df.dropna(subset=["stored_prev"])
    df = df[df["stored_prev"] > 0]

    events: list[dict] = []

    def _add(row, reason: str, detail: str, ratio: float | None, change_pct: float):
        events.append({
            "code":       row.code,
            "event_date": row.trade_date,
            "reason":     reason,
            "detail":     detail,
            "ratio":      Decimal(str(round(ratio, 4))) if ratio is not None else None,
            "change_pct": Decimal(str(round(change_pct, 2))),
            "skip_from":  row.trade_date - timedelta(days=SKIP_BEFORE_DAYS),
            "skip_until": row.trade_date + timedelta(days=SKIP_AFTER_DAYS),
            "created_at": datetime.now(),
        })

    for row in df.itertuples(index=False):
        stored_prev = float(row.stored_prev)
        close = float(row.current_price)
        change_pct = (close / stored_prev - 1) * 100
        prev_info = f"保存済み前日終値 {stored_prev:g}（{row.stored_prev_date}）"

        # 取得元の前日終値と保存値の比較
        if row.prev_close is not None and pd.notna(row.prev_close) and float(row.prev_close) > 0:
            src_prev = float(row.prev_close)
            ratio = src_prev / stored_prev
            if abs(ratio - 1) > PREV_CLOSE_TOLERANCE:
                nearest = split_ratio(ratio)
                if nearest is not None:
                    _add(row, "split_suspected",
                         f"取得元の前日終値 {src_prev:g} が{prev_info}の{fmt_ratio(ratio, nearest)}",
                         ratio, change_pct)
                else:
                    _add(row, "price_mismatch",
                         f"取得元の前日終値 {src_prev:g} と{prev_info}が {(ratio - 1) * 100:+.1f}% 不一致",
                         ratio, change_pct)

        # 終値の不連続なジャンプ
        jump = close / stored_prev
        jump_split = split_ratio(jump) if (jump >= CLOSE_JUMP_RATIO or jump <= 1 / CLOSE_JUMP_RATIO) else None
        if jump_split is not None:
            _add(row, "split_suspected",
                 f"終値 {close:g} が{prev_info}の{fmt_ratio(jump, jump_split)}水準に変化",
                 None, change_pct)
        elif abs(change_pct) >= EXTREME_MOVE_PCT:
            _add(row, "extreme_move",
                 f"終値 {close:g}、{prev_info}から {change_pct:+.1f}%",
                 None, change_pct)

    # 同一 (code, event_date, reason) は1件にまとめる（前日終値と終値ジャンプの両方で分割判定された場合）
    uniq: dict[tuple, dict] = {}
    for e in events:
        uniq.setdefault((e["code"], e["event_date"], e["reason"]), e)
    return list(uniq.values())


def main() -> None:
    start = datetime.now()
    log.info("=== 株価異常検出バッチ 開始 ===")

    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT sp.code, sp.trade_date, sp.prev_close, sp.current_price
            FROM trader_schema.stock_price sp
            JOIN trader_schema.stock_master sm ON sp.code = sm.code
            WHERE sm."isDelisted" = false
              AND sp.current_price IS NOT NULL
        """)).fetchall()

    if not rows:
        log.info("処理対象データなし")
        return

    df = pd.DataFrame(rows, columns=["code", "trade_date", "prev_close", "current_price"])
    log.info("対象銘柄: %d 件、対象行: %d 行", df["code"].nunique(), len(df))

    events = detect(df)
    for reason, cnt in pd.Series([e["reason"] for e in events]).value_counts().items():
        log.info("  %s: %d 件", reason, cnt)

    if not events:
        log.info("異常なし")
        log.info("=== 株価異常検出バッチ 終了 ===")
        return

    CHUNK = 500
    with SessionLocal() as db:
        for i in range(0, len(events), CHUNK):
            stmt = pg_insert(SignalSkip).values(events[i:i + CHUNK])
            stmt = stmt.on_conflict_do_update(
                constraint="uq_skip_code_date_reason",
                set_={c: stmt.excluded[c] for c in ["detail", "ratio", "change_pct", "skip_from", "skip_until"]},
            )
            db.execute(stmt)
        db.commit()

    elapsed = (datetime.now() - start).total_seconds()
    log.info("完了: %d 件保存 (%.1f 秒)", len(events), elapsed)
    log.info("=== 株価異常検出バッチ 終了 ===")


if __name__ == "__main__":
    main()
