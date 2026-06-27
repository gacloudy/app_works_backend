"""
JPX から上場銘柄一覧（data_j.xls）をダウンロードし、
プライム（内国株式）の銘柄を stock_master テーブルに登録するバッチ。

実行方法:
    cd backend
    .venv\Scripts\python -m batch.sync_stock_master
"""

import io
import sys
import os
import logging
from datetime import datetime

import httpx
from bs4 import BeautifulSoup
import openpyxl
import xlrd
from dotenv import load_dotenv
from sqlalchemy.dialects.postgresql import insert

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv()

from app.database import SessionLocal, engine
from app.models.stock_master import StockMaster

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

JPX_LIST_PAGE = "https://www.jpx.co.jp/markets/statistics-equities/misc/01.html"
JPX_FALLBACK_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"
JPX_BASE = "https://www.jpx.co.jp"

PRIME_MARKET_LABEL = "プライム（内国株式）"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.jpx.co.jp/",
    "Accept-Language": "ja,en-US;q=0.9",
}


def find_excel_url(client: httpx.Client) -> str:
    """JPX ページを解析して data_j.xls の URL を取得する。失敗時はフォールバック URL を返す。"""
    try:
        resp = client.get(JPX_LIST_PAGE, headers=HEADERS, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "data_j.xls" in href:
                url = href if href.startswith("http") else JPX_BASE + href
                log.info("Excel URL を発見: %s", url)
                return url
        log.warning("ページから Excel URL を取得できませんでした。フォールバック URL を使用します。")
    except Exception as e:
        log.warning("ページ取得に失敗しました (%s)。フォールバック URL を使用します。", e)
    return JPX_FALLBACK_URL


def download_excel(client: httpx.Client, url: str) -> bytes:
    """Excel ファイルをダウンロードしてバイト列で返す。"""
    log.info("ダウンロード中: %s", url)
    resp = client.get(url, headers=HEADERS, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    log.info("ダウンロード完了 (%d bytes)", len(resp.content))
    return resp.content


def parse_excel(data: bytes) -> list[dict]:
    """Excel を解析してプライム（内国株式）の銘柄リストを返す。"""
    records = []

    # ファイル形式を判定（PK マジックバイト = xlsx）
    is_xlsx = data[:2] == b"PK"

    if is_xlsx:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
    else:
        wb = xlrd.open_workbook(file_contents=data)
        ws = wb.sheet_by_index(0)
        rows = [ws.row_values(i) for i in range(ws.nrows)]

    if not rows:
        raise ValueError("Excel にデータがありません")

    # 1 行目がヘッダー
    header = [str(h).strip() if h is not None else "" for h in rows[0]]
    log.info("ヘッダー: %s", header)

    # 列インデックスを特定
    def col(name: str) -> int:
        for i, h in enumerate(header):
            if name in h:
                return i
        raise ValueError(f"列 '{name}' が見つかりません。ヘッダー: {header}")

    idx_code     = col("コード")
    idx_name     = col("銘柄名")
    idx_market   = col("市場・商品区分")
    idx_industry = col("33業種区分")

    for row in rows[1:]:
        if not row or not row[idx_code]:
            continue
        market = str(row[idx_market]).strip()
        if market != PRIME_MARKET_LABEL:
            continue
        code     = str(row[idx_code]).strip().split(".")[0]  # 数値の場合 "7203.0" → "7203"
        name     = str(row[idx_name]).strip()
        industry = str(row[idx_industry]).strip()
        if code and name:
            records.append({"code": code, "name": name, "industry": industry, "market": market})

    log.info("対象銘柄数: %d 件", len(records))
    return records


def upsert_stocks(records: list[dict]) -> tuple[int, int, int, int]:
    """stock_master に upsert し、Excel 未掲載銘柄を上場廃止扱いにする。
    Returns (inserted, revived, updated, delisted) の件数。
    """
    if not records:
        return 0, 0, 0, 0

    active_codes = {r["code"] for r in records}
    inserted = revived = updated = delisted = 0

    with SessionLocal() as db:
        # --- Excel 掲載銘柄を upsert（isDelisted = False に戻す） ---
        for rec in records:
            existing = db.query(StockMaster).filter(StockMaster.code == rec["code"]).first()
            if existing:
                existing.name       = rec["name"]
                existing.industry   = rec["industry"]
                existing.market     = rec["market"]
                if existing.is_delisted:
                    log.info("復活: %s %s", rec["code"], rec["name"])
                    existing.is_delisted = False
                    revived += 1
                else:
                    updated += 1
            else:
                db.add(StockMaster(**rec))  # is_delisted は model default (False)
                inserted += 1

        # --- Excel 未掲載の銘柄を上場廃止に変更 ---
        newly_delisted = (
            db.query(StockMaster)
            .filter(StockMaster.code.notin_(active_codes))
            .filter(StockMaster.is_delisted == False)  # noqa: E712
            .all()
        )
        for stock in newly_delisted:
            log.info("上場廃止: %s %s", stock.code, stock.name)
            stock.is_delisted = True
            delisted += 1

        db.commit()

    return inserted, revived, updated, delisted


def main():
    start = datetime.now()
    log.info("=== stock_master 同期バッチ 開始 ===")

    with httpx.Client() as client:
        url = find_excel_url(client)
        data = download_excel(client, url)

    records = parse_excel(data)
    inserted, revived, updated, delisted = upsert_stocks(records)

    elapsed = (datetime.now() - start).total_seconds()
    log.info(
        "完了: 新規 %d / 復活 %d / 更新 %d / 上場廃止 %d (%.1f 秒)",
        inserted, revived, updated, delisted, elapsed,
    )
    log.info("=== stock_master 同期バッチ 終了 ===")


if __name__ == "__main__":
    main()
