"""
内閣府の祝日 CSV をダウンロードし、holiday_master テーブルに同期するバッチ。

実行方法:
    cd app_works_backend
    .venv\\Scripts\\python batch\\sync_holidays.py
"""

import csv
import io
import logging
import os
import sys
from datetime import datetime

import httpx
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv()

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import SessionLocal
from app.models.holiday_master import HolidayMaster

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

HOLIDAY_CSV_URL = "https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv"


def fetch_csv(client: httpx.Client) -> str:
    log.info("祝日CSV ダウンロード中: %s", HOLIDAY_CSV_URL)
    resp = client.get(HOLIDAY_CSV_URL, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    content = resp.content.decode("shift_jis")
    log.info("ダウンロード完了 (%d bytes)", len(resp.content))
    return content


def parse_csv(content: str) -> list[dict]:
    records = []
    reader = csv.reader(io.StringIO(content))
    next(reader)  # ヘッダー行をスキップ
    for row in reader:
        if len(row) < 2:
            continue
        date_str, name = row[0].strip(), row[1].strip()
        if not date_str or not name:
            continue
        try:
            d = datetime.strptime(date_str, "%Y/%m/%d").date()
            records.append({"date": d, "name": name})
        except ValueError:
            log.warning("日付パース失敗: %s", date_str)
    log.info("祝日件数: %d 件", len(records))
    return records


def upsert_holidays(records: list[dict]) -> None:
    now = datetime.now()
    rows = [{"date": r["date"], "name": r["name"], "created_at": now} for r in records]
    with SessionLocal() as db:
        stmt = pg_insert(HolidayMaster).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["date"],
            set_={"name": stmt.excluded.name},
        )
        db.execute(stmt)
        db.commit()


def main() -> None:
    log.info("=== 祝日マスタ同期バッチ 開始 ===")
    with httpx.Client() as client:
        content = fetch_csv(client)
    records = parse_csv(content)
    upsert_holidays(records)
    log.info("完了: %d 件を upsert", len(records))
    log.info("=== 祝日マスタ同期バッチ 終了 ===")


if __name__ == "__main__":
    main()
