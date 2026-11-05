"""
J-Quants API（/v2/equities/bars/daily）から過去の日足を取得し、stock_price に source="jquants" で保存するバッチ。
日々の株価取得（fetch_stock_prices: 野村/Yahoo）が始まる前の期間を埋めるための、一回限りの取り込み用。

- 取得範囲: --from（省略時は保存済みの jquants 分の翌日、なければ契約プランで取れる最古の日）から、
  野村/Yahoo のデータがある最初の日の前日まで。1日1リクエストで全銘柄を取得する。
- 価格・出来高は J-Quants の調整済みの値（AdjO/AdjH/AdjL/AdjC/AdjVo）を保存する。既存の野村/Yahoo のデータは
  その後の株式分割を反映した水準で保存されており、調整済みの値と一致するため（調整前の値だと分割銘柄で段差ができる）。
- prev_close は前取引日の調整済み終値。調整済みの系列には分割による段差がないため、分割の検出対象にもならない。
- stock_master にある銘柄のみ保存する。約定のない日（四本値が Null）は保存しない。
- 日付ごとに「その日の jquants 分を削除 → 挿入」するため、途中で止まっても再実行できる。
- --codes を指定すると、その銘柄だけを保存済みの jquants 期間について銘柄単位で取り直す（1銘柄1リクエスト）。

Free プランは「12週間前〜2年12週間前」、5 リクエスト/分。範囲外の古い日付は 400 になるため読み飛ばす。

取り込み後は、以下を全期間で再計算する必要がある:
    calc_technical --full → detect_price_anomalies → detect_signals --full → update_signal_results
    → calc_market_context → aggregate_stats → aggregate_context_stats → update_disclosure_results

実行方法:
    cd app_works_backend
    .venv\\Scripts\\python batch\\backfill_jquants_prices.py [--from 2024-08-12] [--to 2026-06-18]
    .venv\\Scripts\\python batch\\backfill_jquants_prices.py --codes 8035,8766
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


def fetch(client: httpx.Client, params: dict) -> list[dict]:
    rows: list[dict] = []
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


def to_record(r: dict, code: str, prev_close: float | None, now: datetime) -> dict:
    return {
        "code":          code,
        "trade_date":    date.fromisoformat(r["Date"]),
        "open_price":    r.get("AdjO"),
        "high_price":    r.get("AdjH"),
        "low_price":     r.get("AdjL"),
        "prev_close":    prev_close,
        "volume":        int(r["AdjVo"]) if r.get("AdjVo") is not None else None,
        "current_price": r["AdjC"],
        "source":        SOURCE,
        "is_delisted":   False,
        "created_at":    now,
        "updated_at":    now,
    }


def insert_records(db, records: list[dict]) -> None:
    # 1行ずつ送るとリモートDBでは1日分に数十秒かかるため、複数行 INSERT でまとめて送る
    for j in range(0, len(records), 1000):
        db.execute(insert(StockPrice).values(records[j:j + 1000]))


def refetch_codes(client: httpx.Client, codes: list[str]) -> int:
    """保存済みの jquants 期間について、指定銘柄を銘柄単位で取り直す。"""
    with SessionLocal() as db:
        date_from, date_to = db.execute(text(
            "SELECT MIN(trade_date), MAX(trade_date) FROM trader_schema.stock_price WHERE source = :s"
        ), {"s": SOURCE}).one()
    if date_from is None:
        log.info("保存済みの jquants 分がありません")
        return 0
    log.info("銘柄単位で取り直し: %d 銘柄（%s 〜 %s）", len(codes), date_from, date_to)

    total = 0
    fetch_from = date_from
    for i, code in enumerate(codes, 1):
        try:
            rows = fetch(client, {"code": code, "from": fetch_from.isoformat(), "to": date_to.isoformat()})
        except PlanRangeError as e:
            # Free プランの取得可能期間は日々ずれるため、保存済みの最古日が範囲外になっていることがある。
            # 範囲内の開始日から取り直す（範囲外になった日のこの銘柄の行は、下の DELETE で消える）
            m = re.search(r"(\d{4}-\d{2}-\d{2}) ~", str(e))
            if not m:
                raise
            fetch_from = date.fromisoformat(m.group(1))
            log.info("%s 以降を取得します（契約プランの範囲）", fetch_from)
            rows = fetch(client, {"code": code, "from": fetch_from.isoformat(), "to": date_to.isoformat()})
        rows = sorted((r for r in rows if r.get("AdjC") is not None), key=lambda r: r["Date"])
        now = datetime.now()
        records, prev = [], None
        for r in rows:
            records.append(to_record(r, code, prev, now))
            prev = r["AdjC"]
        with SessionLocal() as db:
            db.execute(text("""
                DELETE FROM trader_schema.stock_price
                WHERE source = :s AND code = :c AND trade_date BETWEEN :f AND :t
            """), {"s": SOURCE, "c": code, "f": date_from, "t": date_to})
            insert_records(db, records)
            db.commit()
        total += len(records)
        log.info("[%d/%d] %s: %d 件", i, len(codes), code, len(records))
    return total


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="date_from", type=date.fromisoformat)
    parser.add_argument("--to", dest="date_to", type=date.fromisoformat)
    parser.add_argument("--codes", help="カンマ区切りの銘柄コード。指定した銘柄だけを銘柄単位で取り直す")
    args = parser.parse_args()

    start = datetime.now()
    log.info("=== J-Quants 過去株価取り込みバッチ 開始 ===")

    api_key = os.environ.get("JQUANTS_API_KEY")
    if not api_key:
        raise RuntimeError("JQUANTS_API_KEY が設定されていません")

    if args.codes:
        with httpx.Client(headers={"x-api-key": api_key}, timeout=120) as client:
            total = refetch_codes(client, [c.strip() for c in args.codes.split(",") if c.strip()])
        elapsed = (datetime.now() - start).total_seconds()
        log.info("完了: %d 件保存 (%.1f 秒)", total, elapsed)
        log.info("=== J-Quants 過去株価取り込みバッチ 終了 ===")
        return

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

    # 前取引日の終値（prev_close 用）。途中再開時は保存済みの直近終値から始める
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
                rows = fetch(client, {"date": d.isoformat()})
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
                if code not in codes or r.get("AdjC") is None:
                    continue
                records.append(to_record(r, code, last_close.get(code), now))
                last_close[code] = float(r["AdjC"])

            with SessionLocal() as db:
                db.execute(text("DELETE FROM trader_schema.stock_price WHERE source = :s AND trade_date = :d"),
                           {"s": SOURCE, "d": d})
                insert_records(db, records)
                db.commit()
            total += len(records)
            if records or i % 20 == 0:
                log.info("[%d/%d] %s: %d 件", i, len(targets), d, len(records))

    elapsed = (datetime.now() - start).total_seconds()
    log.info("完了: %d 件保存 (%.1f 秒)", total, elapsed)
    log.info("=== J-Quants 過去株価取り込みバッチ 終了 ===")


if __name__ == "__main__":
    main()
