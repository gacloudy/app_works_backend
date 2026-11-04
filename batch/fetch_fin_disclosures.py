"""
J-Quants API（/v2/fins/summary）から決算短信・業績予想の修正・配当予想の修正を取得し、
fin_disclosure テーブルに保存するバッチ。stock_master の銘柄（プライム）のみ保存する。

通常モード : 保存済みの最終開示日（初回は START_DATE）から今日まで、1日1リクエストで取得する。
--by-code   : stock_master の全銘柄について、銘柄ごとに全期間を取得する（初回の過去分取り込み用）。
              業績予想の修正を「前回の予想」と比べるため、過去の決算短信が必要になる。

Free プランは「12週間前〜2年12週間前」のデータしか取得できない。範囲外の日付は 400 が返るため、
その日以降の取得は打ち切る（次回以降、範囲に入った日から取得される）。

必要な環境変数: JQUANTS_API_KEY（J-Quants のダッシュボードで発行する API キー）

実行方法:
    cd app_works_backend
    .venv\\Scripts\\python batch\\fetch_fin_disclosures.py
    .venv\\Scripts\\python batch\\fetch_fin_disclosures.py --by-code
"""

import sys
import os
import argparse
import logging
import time
from datetime import date, datetime, timedelta

import httpx
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv()

from app.database import SessionLocal
from app.models.fin_disclosure import FinDisclosure

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

API_URL = "https://api.jquants.com/v2/fins/summary"
START_DATE = date(2026, 6, 1)   # 通常モード初回の取得開始日（株価データの蓄積開始の少し前）
REQUEST_INTERVAL = 1.1          # 秒。/fins/summary はプランによらず 60 リクエスト/分
RATE_LIMIT_WAIT = 120           # 429 のときの待機秒数（API仕様の推奨は1〜2分）

# J-Quants の項目名 → fin_disclosure の列名（金額・配当は数値に変換して保存する）
NUMERIC_FIELDS = {
    "Sales": "sales", "OP": "op", "OdP": "odp", "NP": "np",
    "FSales": "f_sales", "FOP": "f_op", "FOdP": "f_odp", "FNP": "f_np",
    "NxFSales": "nx_f_sales", "NxFOP": "nx_f_op", "NxFOdP": "nx_f_odp", "NxFNp": "nx_f_np",
    "DivAnn": "div_ann", "FDivAnn": "f_div_ann", "NxFDivAnn": "nx_f_div_ann",
}


def to_app_code(jq_code: str) -> str:
    """J-Quants の5桁コード（例: 72030, 285A0）をアプリの4桁コードにする。"""
    return jq_code[:4] if len(jq_code) == 5 and jq_code.endswith("0") else jq_code


def to_date(v: str) -> date | None:
    return date.fromisoformat(v) if v else None


def to_num(v: str) -> float | None:
    try:
        return float(v) if v not in ("", None) else None
    except ValueError:
        return None


def to_record(row: dict, now: datetime) -> dict:
    return {
        "disc_no":       row["DiscNo"],
        "code":          to_app_code(row["Code"]),
        "disc_date":     to_date(row["DiscDate"]),
        "disc_time":     (row.get("DiscTime") or "")[:5],
        "doc_type":      row["DocType"],
        "cur_per_type":  row.get("CurPerType") or None,
        "cur_fy_st":     to_date(row.get("CurFYSt", "")),
        "cur_fy_en":     to_date(row.get("CurFYEn", "")),
        "nxt_fy_st":     to_date(row.get("NxtFYSt", "")),
        "nxt_fy_en":     to_date(row.get("NxtFYEn", "")),
        **{col: to_num(row.get(key, "")) for key, col in NUMERIC_FIELDS.items()},
        "fetched_at":    now,
    }


class PlanRangeError(Exception):
    """契約プランの取得可能期間外を指定した。"""


def fetch(client: httpx.Client, params: dict) -> list[dict]:
    """ページネーションをたどって全件取得する。"""
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


def save(records: list[dict]) -> None:
    if not records:
        return
    update_cols = [c for c in records[0] if c != "disc_no"]
    with SessionLocal() as db:
        for i in range(0, len(records), 500):
            stmt = pg_insert(FinDisclosure).values(records[i:i + 500])
            stmt = stmt.on_conflict_do_update(
                index_elements=["disc_no"], set_={c: stmt.excluded[c] for c in update_cols}
            )
            db.execute(stmt)
        db.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--by-code", action="store_true", help="銘柄ごとに全期間を取得する（初回の過去分取り込み用）")
    args = parser.parse_args()

    start = datetime.now()
    log.info("=== 財務情報取得バッチ 開始 ===")

    api_key = os.environ.get("JQUANTS_API_KEY")
    if not api_key:
        raise RuntimeError("JQUANTS_API_KEY が設定されていません")

    with SessionLocal() as db:
        codes = {r[0] for r in db.execute(text("SELECT code FROM trader_schema.stock_master")).fetchall()}
        last_date = db.execute(text("SELECT MAX(disc_date) FROM trader_schema.fin_disclosure")).scalar()

    total = 0
    with httpx.Client(headers={"x-api-key": api_key}, timeout=60) as client:
        if args.by_code:
            targets = [("code", c) for c in sorted(codes)]
        else:
            # 最終開示日は取得途中だった可能性があるため、その日から取り直す（upsert なので重複しない）
            d = last_date or START_DATE
            targets = []
            while d <= date.today():
                if d.weekday() < 5:
                    targets.append(("date", d.isoformat()))
                d += timedelta(days=1)
        log.info("取得対象: %d 件（%s 指定）", len(targets), "銘柄" if args.by_code else "日付")

        for i, (key, value) in enumerate(targets, 1):
            try:
                rows = fetch(client, {key: value})
            except PlanRangeError as e:
                if args.by_code:
                    log.warning("%s: 取得できませんでした（%s）", value, e)
                    continue
                log.info("%s 以降は契約プランの取得可能期間外のため打ち切ります（%s）", value, e)
                break
            now = datetime.now()
            records = [to_record(r, now) for r in rows if to_app_code(r["Code"]) in codes]
            save(records)
            total += len(records)
            if i % 50 == 0 or not args.by_code:
                log.info("[%d/%d] %s: %d 件", i, len(targets), value, len(records))

    elapsed = (datetime.now() - start).total_seconds()
    log.info("完了: %d 件保存 (%.1f 秒)", total, elapsed)
    log.info("=== 財務情報取得バッチ 終了 ===")


if __name__ == "__main__":
    main()
