"""
J-Quants API（/v2/equities/bars/daily）から過去の日足を取得し、stock_price に source="jquants" で保存するバッチ。
日々の株価取得（fetch_stock_prices: 野村/Yahoo）が始まる前の期間を埋めるための、一回限りの取り込み用。

- 取得範囲: --from（省略時は保存済みの jquants 分の翌日、なければ契約プランで取れる最古の日）から、
  野村/Yahoo のデータがある最初の日の前日まで。1日1リクエストで全銘柄を取得する。
- 価格は既存データと同じく調整前の値（O/H/L/C/Vo）を保存する。
- prev_close は「前取引日の終値 × 当日の調整係数（AdjFactor）」とする。株式分割の権利落ち日には
  取引所の基準値と同じく分割後の水準になるため、detect_price_anomalies の分割検出がそのまま働く。
- stock_master にある銘柄のみ保存する。約定のない日（四本値が Null）は保存しない。
- 日付ごとに「その日の jquants 分を削除 → 挿入」するため、途中で止まっても再実行できる。

Free プランは「12週間前〜2年12週間前」、5 リクエスト/分。範囲外の古い日付は 400 になるため読み飛ばす。

取り込み後は、以下を全期間で再計算する必要がある:
    calc_technical --full → detect_price_anomalies → detect_signals --full → update_signal_results
    → calc_market_context → aggregate_stats → aggregate_context_stats → update_disclosure_results

実行方法:
    cd app_works_backend
    .venv\\Scripts\\python batch\\backfill_jquants_prices.py [--from 2024-08-12] [--to 2026-06-18]
"""

import sys
import os
import argparse
import logging
import re
import time
from datetime import date, datetime, timedelta

import httpx
from dotenv import load_dotenv
from sqlalchemy import insert, text

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv()

from app.database import SessionLocal
from app.models.stock_price import StockPrice
from batch.fetch_fin_disclosures import to_app_code

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)

API_URL = "https://api.jquants.com/v2/equities/bars/daily"
SOURCE = "jquants"
EARLIEST = date(2024, 1, 1)   # 契約プランの範囲外は 400 で読み飛ばすため、十分古い日から試す
REQUEST_INTERVAL = 12.5       # 秒。Free プランは 5 リクエスト/分
RATE_LIMIT_WAIT = 120


class PlanRangeError(Exception):
    """契約プランの取得可能期間外を指定した。"""


def fetch_date(client: httpx.Client, d: date) -> list[dict]:
    rows: list[dict] = []
    params = {"date": d.isoformat()}
    while True:
        time.sleep(REQUEST_INTERVAL)
        res = client.get(API_URL, params=params)
        if res.status_code == 429:
            log.warning("レートリミットに達したため %d 秒待機します", RATE_LIMIT_WAIT)
            time.sleep(RATE_LIMIT_WAIT)
            continue
        if res.status_code == 400:
            raise PlanRangeError(res.text)
        res.raise_for_status()
        body = res.json()
        rows.extend(body.get("data", []))
        if not body.get("pagination_key"):
            return rows
        params = {**params, "pagination_key": body["pagination_key"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="date_from", type=date.fromisoformat)
    parser.add_argument("--to", dest="date_to", type=date.fromisoformat)
    args = parser.parse_args()

    start = datetime.now()
    log.info("=== J-Quants 過去株価取り込みバッチ 開始 ===")

    api_key = os.environ.get("JQUANTS_API_KEY")
    if not api_key:
        raise RuntimeError("JQUANTS_API_KEY が設定されていません")

    with SessionLocal() as db:
        codes = {r[0] for r in db.execute(text("SELECT code FROM trader_schema.stock_master")).fetchall()}
        holidays = {r[0] for r in db.execute(text("SELECT date FROM trader_schema.holiday_master")).fetchall()}
        first_daily = db.execute(text(
            "SELECT MIN(trade_date) FROM trader_schema.stock_price WHERE source IS DISTINCT FROM :s"
        ), {"s": SOURCE}).scalar()
        last_backfilled = db.execute(text(
            "SELECT MAX(trade_date) FROM trader_schema.stock_price WHERE source = :s"
        ), {"s": SOURCE}).scalar()

    date_to = args.date_to or ((first_daily - timedelta(days=1)) if first_daily else date.today())
    date_from = args.date_from or ((last_backfilled + timedelta(days=1)) if last_backfilled else EARLIEST)
    targets = []
    d = date_from
    while d <= date_to:
        if d.weekday() < 5 and d not in holidays:
            targets.append(d)
        d += timedelta(days=1)
    log.info("取得期間: %s 〜 %s（%d 営業日）", date_from, date_to, len(targets))

    # 前取引日の終値（prev_close の計算用）。途中再開時は保存済みの直近終値から始める
    with SessionLocal() as db:
        last_close = dict(db.execute(text("""
            SELECT DISTINCT ON (code) code, current_price FROM trader_schema.stock_price
            WHERE trade_date < :d AND current_price IS NOT NULL
            ORDER BY code, trade_date DESC
        """), {"d": date_from}).fetchall())
    last_close = {k: float(v) for k, v in last_close.items()}

    total = 0
    covered_from: date | None = None
    with httpx.Client(headers={"x-api-key": api_key}, timeout=120) as client:
        for i, d in enumerate(targets, 1):
            if covered_from and d < covered_from:
                continue
            try:
                rows = fetch_date(client, d)
            except PlanRangeError as e:
                # 契約プランの範囲より古い日付。エラー文の "covers the following dates: YYYY-MM-DD ~" から開始日を読む
                m = re.search(r"(\d{4}-\d{2}-\d{2}) ~", str(e))
                covered_from = date.fromisoformat(m.group(1)) if m else None
                log.info("%s は契約プランの範囲外のため、%s から取得します", d, covered_from)
                continue
            now = datetime.now()
            records = []
            for r in rows:
                code = to_app_code(r["Code"])
                if code not in codes or r.get("C") is None:
                    continue
                prev = last_close.get(code)
                factor = r.get("AdjFactor") or 1.0
                records.append({
                    "code":          code,
                    "trade_date":    d,
                    "open_price":    r.get("O"),
                    "high_price":    r.get("H"),
                    "low_price":     r.get("L"),
                    "prev_close":    round(prev * factor, 1) if prev is not None else None,
                    "volume":        int(r["Vo"]) if r.get("Vo") is not None else None,
                    "current_price": r["C"],
                    "source":        SOURCE,
                    "is_delisted":   False,
                    "created_at":    now,
                    "updated_at":    now,
                })
                last_close[code] = float(r["C"])

            with SessionLocal() as db:
                db.execute(text("DELETE FROM trader_schema.stock_price WHERE source = :s AND trade_date = :d"),
                           {"s": SOURCE, "d": d})
                # 1行ずつ送るとリモートDBでは1日分に数十秒かかるため、複数行 INSERT でまとめて送る
                for j in range(0, len(records), 1000):
                    db.execute(insert(StockPrice).values(records[j:j + 1000]))
                db.commit()
            total += len(records)
            if records or i % 20 == 0:
                log.info("[%d/%d] %s: %d 件", i, len(targets), d, len(records))

    elapsed = (datetime.now() - start).total_seconds()
    log.info("完了: %d 件保存 (%.1f 秒)", total, elapsed)
    log.info("=== J-Quants 過去株価取り込みバッチ 終了 ===")


if __name__ == "__main__":
    main()
