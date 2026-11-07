"""
その日にシグナルが出た銘柄の中から、「その銘柄で過去によく効いていたサイン」を選び、
翌営業日の買い時・売り時として daily_picks に保存するバッチ（1日最大 MAX_PICKS 件）。
detect_signals の後に実行する。

選び方（すべて pick_date までに結果が確定していた過去のシグナルだけで計算し、未来のデータは使わない）
  - 売買: シグナルの翌営業日の始値で買い（売り）、シグナル日から HOLD_DAYS 営業日後の終値で売る（買い戻す）想定
      買いシグナル: 1回の値 = 損益 − 手数料（往復 COST_PCT %）
      売りシグナル: 1回の値 = 避けられた値下がり（= −損益）。空売りは前提にしない
  - 候補: その銘柄でそのサインの結果が MIN_COUNT 回以上あり、勝率 MIN_WIN_RATE % 以上、1回平均がプラス
  - 並べ順: score = (回数 × 1回平均 + PRIOR_COUNT × 全銘柄平均) / (回数 + PRIOR_COUNT)
            回数が少ないほど全銘柄の平均に寄せ、少ない回数の偶然の好成績を上位にしにくくする
  - 1銘柄につき1件（同じ日に複数のサインが出たら score の高い方）

通常（引数なし）: 最新のシグナル日について選び直して保存する（is_live = true）
--backfill      : 推奨がまだ保存されていない過去の日付をすべて同じ方法で計算する（is_live = false）

実行方法:
    cd app_works_backend
    .venv\\Scripts\\python batch\\select_daily_picks.py
    .venv\\Scripts\\python batch\\select_daily_picks.py --backfill
"""

import sys
import os
import argparse
import bisect
import logging
from collections import defaultdict
from datetime import date, datetime

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv()

from app.database import SessionLocal
from app.models.daily_pick import DailyPick

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

MAX_PICKS = 3
HOLD_DAYS = 20
COST_PCT = 0.1
MIN_COUNT = 8
MIN_WIN_RATE = 60.0
PRIOR_COUNT = 8
SIGNAL_SIDE = {
    "golden_cross": "buy", "rsi_oversold": "buy", "bb_lower_touch": "buy", "volume_surge_up": "buy",
    "dead_cross": "sell", "rsi_overbought": "sell", "bb_upper_touch": "sell",
}


class PastTrades:
    """シグナルごとの「結果が確定した日（exit_date）」と値を持ち、ある日までの成績を引けるようにする。"""

    def __init__(self):
        # (code, signal_type) → 結果確定日の昇順の [(exit_date, value)]
        self.by_stock: dict[tuple[str, str], list[tuple[date, float]]] = defaultdict(list)
        # signal_type → 結果確定日の昇順の日付と、値の累積和（全銘柄平均用）
        self.by_type: dict[str, list[tuple[date, float]]] = defaultdict(list)
        self._type_dates: dict[str, list[date]] = {}
        self._type_cumsum: dict[str, list[float]] = {}

    def add(self, code: str, signal_type: str, exit_date: date, value: float) -> None:
        self.by_stock[(code, signal_type)].append((exit_date, value))
        self.by_type[signal_type].append((exit_date, value))

    def finalize(self) -> None:
        for rows in self.by_stock.values():
            rows.sort()
        for t, rows in self.by_type.items():
            rows.sort()
            self._type_dates[t] = [d for d, _ in rows]
            cum, s = [], 0.0
            for _, v in rows:
                s += v
                cum.append(s)
            self._type_cumsum[t] = cum

    def stock_values(self, code: str, signal_type: str, as_of: date) -> list[float]:
        rows = self.by_stock.get((code, signal_type), [])
        n = bisect.bisect_right(rows, (as_of, float("inf")))
        return [v for _, v in rows[:n]]

    def type_mean(self, signal_type: str, as_of: date) -> float | None:
        dates = self._type_dates.get(signal_type, [])
        n = bisect.bisect_right(dates, as_of)
        return self._type_cumsum[signal_type][n - 1] / n if n else None


def load(db):
    prices = db.execute(text("""
        SELECT sp.code, sp.trade_date, sp.open_price, sp.current_price
        FROM trader_schema.stock_price sp
        JOIN trader_schema.stock_master sm ON sm.code = sp.code AND sm."isDelisted" = false
        WHERE sp.current_price IS NOT NULL
        ORDER BY sp.code, sp.trade_date
    """)).fetchall()
    signals = db.execute(text("""
        SELECT sh.code, sh.signal_date, sh.signal_type
        FROM trader_schema.signal_history sh
        JOIN trader_schema.stock_master sm ON sm.code = sh.code AND sm."isDelisted" = false
    """)).fetchall()
    return prices, signals


def build(prices, signals) -> tuple[PastTrades, dict, dict]:
    """過去の売買結果と、日付ごとのシグナル一覧・終値を作る。"""
    series: dict[str, tuple[list, list, list]] = {}
    for code, d, o, c in prices:
        s = series.setdefault(code, ([], [], []))
        s[0].append(d)
        s[1].append(float(o) if o is not None else None)
        s[2].append(float(c))
    pos = {code: {d: i for i, d in enumerate(s[0])} for code, s in series.items()}

    past = PastTrades()
    by_date: dict[date, list[tuple[str, str]]] = defaultdict(list)
    closes: dict[tuple[str, date], float] = {}
    for code, d, stype in signals:
        side = SIGNAL_SIDE.get(stype)
        if side is None or code not in series or d not in pos[code]:
            continue
        dates, opens, cls = series[code]
        i = pos[code][d]
        by_date[d].append((code, stype))
        closes[(code, d)] = cls[i]
        if i + HOLD_DAYS < len(dates) and opens[i + 1]:
            raw = (cls[i + HOLD_DAYS] / opens[i + 1] - 1) * 100
            value = raw - COST_PCT if side == "buy" else -raw
            past.add(code, stype, dates[i + HOLD_DAYS], value)
    past.finalize()
    return past, by_date, closes


def select(pick_date: date, past: PastTrades, by_date: dict, closes: dict) -> list[dict]:
    """pick_date に出たシグナルから、最大 MAX_PICKS 件の推奨を選ぶ。"""
    best: dict[str, dict] = {}
    for code, stype in by_date.get(pick_date, []):
        values = past.stock_values(code, stype, pick_date)
        n = len(values)
        if n < MIN_COUNT:
            continue
        avg = sum(values) / n
        win_rate = sum(v > 0 for v in values) / n * 100
        if win_rate < MIN_WIN_RATE or avg <= 0:
            continue
        prior = past.type_mean(stype, pick_date)
        score = (n * avg + PRIOR_COUNT * (prior or 0.0)) / (n + PRIOR_COUNT)
        cand = {
            "code": code, "signal_type": stype, "side": SIGNAL_SIDE[stype],
            "close_price": round(closes[(code, pick_date)], 1), "hold_days": HOLD_DAYS,
            "past_count": n, "past_win_rate": round(win_rate, 2), "past_avg": round(avg, 4),
            "all_stocks_avg": round(prior, 4) if prior is not None else None, "score": round(score, 4),
        }
        if code not in best or cand["score"] > best[code]["score"]:
            best[code] = cand
    picks = sorted(best.values(), key=lambda c: c["score"], reverse=True)[:MAX_PICKS]
    return [{"pick_date": pick_date, "rank": r, **p} for r, p in enumerate(picks, 1)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", action="store_true", help="推奨が保存されていない過去の日付をすべて計算する")
    args = parser.parse_args()

    start = datetime.now()
    log.info("=== 売買推奨の選定バッチ 開始 ===")

    with SessionLocal() as db:
        prices, signals = load(db)
        saved_dates = {r[0] for r in db.execute(text("SELECT DISTINCT pick_date FROM trader_schema.daily_picks")).fetchall()}
    past, by_date, closes = build(prices, signals)
    if not by_date:
        log.info("シグナルなし")
        log.info("=== 売買推奨の選定バッチ 終了 ===")
        return

    latest = max(by_date)
    if args.backfill:
        targets = [d for d in sorted(by_date) if d < latest and d not in saved_dates]
        is_live = False
    else:
        targets = [latest]
        is_live = True
    log.info("対象日: %d 日（%s）", len(targets), "遡って計算" if args.backfill else latest)

    now = datetime.now()
    records = []
    for d in targets:
        records.extend({**p, "is_live": is_live, "created_at": now} for p in select(d, past, by_date, closes))

    with SessionLocal() as db:
        if not args.backfill:
            # 最新日は同じ夜に再実行しても同じ結果になるよう、選び直して置き換える
            db.execute(text("DELETE FROM trader_schema.daily_picks WHERE pick_date = :d"), {"d": latest})
        for i in range(0, len(records), 1000):
            db.execute(pg_insert(DailyPick).values(records[i:i + 1000]))
        db.commit()

    days_with_picks = len({r["pick_date"] for r in records})
    elapsed = (datetime.now() - start).total_seconds()
    log.info("完了: %d 日中 %d 日で推奨あり、計 %d 件保存 (%.1f 秒)", len(targets), days_with_picks, len(records), elapsed)
    log.info("=== 売買推奨の選定バッチ 終了 ===")


if __name__ == "__main__":
    main()
