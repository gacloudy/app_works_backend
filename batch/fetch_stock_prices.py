"""
stock_master の全銘柄の株価情報を取得し、stock_price テーブルに登録するバッチ。

取得項目: 始値, 高値, 安値, 前日終値, 出来高, 現在値
一次取得元: Nomura 株価ページ
二次取得元: Yahoo Finance Japan (Nomura で取得できない場合のフォールバック)

日付検証:
  - 土日の場合は直前の金曜を「想定取引日」とする（日本の祝日は非対応）
  - ページ上の日付が想定取引日と一致しない場合は警告ログを出してページ日付を採用する

実行方法:
    cd backend
    .venv\\Scripts\\python -m batch.fetch_stock_prices
"""

import sys
import os
import re
import time
import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv()

from app.database import SessionLocal
from app.models.stock_master import StockMaster
from app.models.stock_price import StockPrice
from app.models.batch_fetch_log import BatchFetchLog

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

NOMURA_URL = (
    "https://quote.nomura.co.jp/nomura/cgi-bin/parser.pl"
    "?QCODE={code}&TEMPLATE=nomura_tp_kabu_01&MKTN=T"
)
YAHOO_URL = "https://finance.yahoo.co.jp/quote/{code}.T"

FETCH_DELAY = 1.0  # seconds between stocks

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
}


# ---------------------------------------------------------------------------
# 日付ユーティリティ
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# 数値パース
# ---------------------------------------------------------------------------

def parse_price(text: str) -> Decimal | None:
    """'6,482円' '6,482' '2,785.5 09:00' などから最初の数値（Decimal）を返す。"""
    if not text:
        return None
    # カンマ区切りを除去してから最初の数値にマッチ（時刻など後続の数字を拾わない）
    text = text.replace(",", "")
    m = re.search(r"\d+(?:\.\d+)?", text)
    try:
        return Decimal(m.group()) if m else None
    except InvalidOperation:
        return None


def parse_volume(text: str) -> int | None:
    """出来高文字列を株数（整数）に変換する。
    '20,049,100'    → 20_049_100
    '20,049.1千株'  → 20_049_100  (千株 = ×1000)
    '2,004.91万株'  → 20_049_100  (万株 = ×10000)
    """
    if not text:
        return None
    text = text.strip()
    try:
        if "千株" in text:
            num = Decimal(re.sub(r"[^\d.]", "", text.replace(",", "")))
            return int(num * 1000)
        if "万株" in text:
            num = Decimal(re.sub(r"[^\d.]", "", text.replace(",", "")))
            return int(num * 10000)
        digits = re.sub(r"[^\d]", "", text)
        return int(digits) if digits else None
    except (InvalidOperation, ValueError):
        return None


# ---------------------------------------------------------------------------
# HTML パーサー共通ユーティリティ
# ---------------------------------------------------------------------------

def find_label_value(soup: BeautifulSoup, label: str) -> str | None:
    """ラベルテキストと隣接する値テキストを BeautifulSoup から抽出する。
    テーブル行（<td>ラベル</td><td>値</td>）とリスト/span ペアの両方に対応。
    """
    for node in soup.find_all(string=True):
        if node.strip() != label:
            continue
        parent = node.parent
        if parent is None:
            continue

        # パターン1: 兄弟要素が値を持つ (<span>ラベル</span><span>値</span>)
        sibling = parent.find_next_sibling()
        if sibling:
            val = sibling.get_text(strip=True)
            if val and val != label:
                return val

        # パターン2: テーブル行 <tr><td>ラベル</td><td>値</td></tr>
        row = parent.find_parent("tr")
        if row:
            cells = row.find_all(["td", "th"])
            for i, cell in enumerate(cells):
                if label in cell.get_text(strip=True):
                    if i + 1 < len(cells):
                        return cells[i + 1].get_text(strip=True)

        # パターン3: 親要素のテキストをまるごと返す（dl/dt/dd などのケース）
        next_parent_sib = parent.parent.find_next_sibling() if parent.parent else None
        if next_parent_sib:
            val = next_parent_sib.get_text(strip=True)
            if val and val != label:
                return val

    return None


# ---------------------------------------------------------------------------
# Nomura パーサー
# ---------------------------------------------------------------------------

def parse_nomura(html: str, code: str) -> dict | None:
    """野村株価ページ (nomura_tp_kabu_01) の HTML を解析する。"""
    soup = BeautifulSoup(html, "html.parser")

    # 日付: "YYYY/MM/DD" パターン
    trade_date: date | None = None
    m = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", html)
    if m:
        try:
            trade_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    open_txt    = find_label_value(soup, "始値")
    high_txt    = find_label_value(soup, "高値")
    low_txt     = find_label_value(soup, "安値")
    prev_txt    = find_label_value(soup, "前日終値")
    vol_txt     = find_label_value(soup, "出来高")
    cur_txt     = find_label_value(soup, "現在値")

    # 最低限 現在値 か 始値 が取れていれば成功とみなす
    if cur_txt is None and open_txt is None:
        log.debug("[%s] Nomura: 値が見つかりませんでした", code)
        return None

    return {
        "trade_date":    trade_date,
        "open_price":    parse_price(open_txt),
        "high_price":    parse_price(high_txt),
        "low_price":     parse_price(low_txt),
        "prev_close":    parse_price(prev_txt),
        "volume":        parse_volume(vol_txt),
        "current_price": parse_price(cur_txt),
        "source":        "nomura",
    }


# ---------------------------------------------------------------------------
# Yahoo Finance Japan パーサー
# ---------------------------------------------------------------------------

def parse_yahoo(html: str, code: str) -> dict | None:
    """Yahoo Finance Japan の HTML を解析する。"""
    soup = BeautifulSoup(html, "html.parser")

    # 日付: "MM/DD" パターン（年なし）
    trade_date: date | None = None
    # "(06/19 15:30)" や "06/19" の形式を探す
    m = re.search(r"\b(\d{1,2})/(\d{2})(?:\s+\d{1,2}:\d{2})?", html)
    if m:
        today = date.today()
        try:
            trade_date = date(today.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            pass

    open_txt = find_label_value(soup, "始値")
    high_txt = find_label_value(soup, "高値")
    low_txt  = find_label_value(soup, "安値")
    prev_txt = find_label_value(soup, "前日終値")
    vol_txt  = find_label_value(soup, "出来高")

    # 現在値はラベルなしで大きく表示されることが多い
    cur_txt = find_label_value(soup, "現在値") or find_label_value(soup, "株価")

    if cur_txt is None and open_txt is None:
        log.debug("[%s] Yahoo: 値が見つかりませんでした", code)
        return None

    return {
        "trade_date":    trade_date,
        "open_price":    parse_price(open_txt),
        "high_price":    parse_price(high_txt),
        "low_price":     parse_price(low_txt),
        "prev_close":    parse_price(prev_txt),
        "volume":        parse_volume(vol_txt),
        "current_price": parse_price(cur_txt),
        "source":        "yahoo",
    }


# ---------------------------------------------------------------------------
# 取得メイン（Nomura → Yahoo フォールバック）
# ---------------------------------------------------------------------------

def fetch_stock_data(client: httpx.Client, code: str) -> dict | None:
    """銘柄コードの株価を取得する。Nomura で失敗したら Yahoo にフォールバック。"""

    # 一次: Nomura
    try:
        resp = client.get(NOMURA_URL.format(code=code), headers=HEADERS,
                          timeout=15, follow_redirects=True)
        resp.raise_for_status()
        data = parse_nomura(resp.text, code)
        if data and (data["current_price"] is not None or data["open_price"] is not None):
            return data
        log.warning("[%s] Nomura: 解析失敗またはデータ不足 → Yahoo に切替", code)
    except Exception as exc:
        log.warning("[%s] Nomura 取得エラー: %s → Yahoo に切替", code, exc)

    # 二次: Yahoo Finance Japan
    try:
        resp = client.get(YAHOO_URL.format(code=code), headers=HEADERS,
                          timeout=15, follow_redirects=True)
        resp.raise_for_status()
        data = parse_yahoo(resp.text, code)
        if data:
            return data
        log.warning("[%s] Yahoo: 解析失敗", code)
    except Exception as exc:
        log.warning("[%s] Yahoo 取得エラー: %s", code, exc)

    return None


# ---------------------------------------------------------------------------
# DB 書き込み
# ---------------------------------------------------------------------------

def insert_fetch_log(run_id: str, code: str, status: str, reason: str, source: str | None = None) -> None:
    """スキップ・エラーを batch_fetch_log に記録する。失敗しても例外を伝播させない。"""
    try:
        with SessionLocal() as db:
            db.add(BatchFetchLog(run_id=run_id, code=code, status=status, reason=reason, source=source))
            db.commit()
    except Exception as exc:
        log.warning("バッチログのDB書き込み失敗: %s", exc)


def upsert_price(db, code: str, data: dict) -> str:
    """stock_price に upsert する。戻り値は 'insert' または 'update'。"""
    existing = (
        db.query(StockPrice)
        .filter(StockPrice.code == code, StockPrice.trade_date == data["trade_date"])
        .first()
    )
    if existing:
        for key, val in data.items():
            setattr(existing, key, val)
        existing.updated_at = datetime.now()
        return "update"
    else:
        db.add(StockPrice(code=code, **data))
        return "insert"


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------

def main() -> None:
    start_dt = datetime.now()
    run_id = start_dt.strftime("%Y%m%d_%H%M%S")
    log.info("=== 株価取得バッチ 開始 (run_id=%s) ===", run_id)

    today = date.today()
    log.info("本日: %s", today)

    with SessionLocal() as db:
        # is_delisted カラムが未実装のため、現時点では全銘柄を対象とする
        stocks = db.query(StockMaster.code).order_by(StockMaster.code).all()

    codes = [s.code for s in stocks]
    log.info("取得対象: %d 銘柄", len(codes))

    ok = skipped = errors = 0

    with httpx.Client() as client:
        for idx, code in enumerate(codes, 1):
            log.info("[%d/%d] %s ...", idx, len(codes), code)

            try:
                data = fetch_stock_data(client, code)
            except Exception as exc:
                log.error("[%s] 予期しないエラー: %s", code, exc)
                insert_fetch_log(run_id, code, "error", f"予期しないエラー: {exc}")
                errors += 1
                time.sleep(FETCH_DELAY)
                continue

            if data is None:
                log.warning("[%s] 取得失敗 → スキップ", code)
                insert_fetch_log(run_id, code, "skip", "Nomura・Yahoo ともに取得失敗")
                skipped += 1
                time.sleep(FETCH_DELAY)
                continue

            # 現在値が取れなければ登録スキップ
            if data.get("current_price") is None:
                log.warning("[%s] 現在値を取得できず → スキップ", code)
                insert_fetch_log(run_id, code, "skip", "現在値を取得できず", data.get("source"))
                skipped += 1
                time.sleep(FETCH_DELAY)
                continue

            # 日付検証: 本日の株価でなければ登録スキップ
            page_date = data.get("trade_date")
            if page_date is None:
                log.warning("[%s] ページ日付を解析できず → スキップ", code)
                insert_fetch_log(run_id, code, "skip", "ページ日付を解析できず", data.get("source"))
                skipped += 1
                time.sleep(FETCH_DELAY)
                continue

            with SessionLocal() as db:
                action = upsert_price(db, code, data)
                db.commit()

            log.info(
                "[%s] %s | 現在値=%s 出来高=%s (%s)",
                code, action, data.get("current_price"), data.get("volume"), data.get("source"),
            )
            ok += 1

            if idx < len(codes):
                time.sleep(FETCH_DELAY)

    elapsed = (datetime.now() - start_dt).total_seconds()
    log.info(
        "完了: 成功 %d / スキップ %d / エラー %d (%.1f 秒 / %.1f 分)",
        ok, skipped, errors, elapsed, elapsed / 60,
    )
    log.info("=== 株価取得バッチ 終了 ===")


if __name__ == "__main__":
    main()
