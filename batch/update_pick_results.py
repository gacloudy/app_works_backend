"""
「今日の売買サイン」で出した推奨（daily_picks）が、その後どうなったかを pick_results に記録するバッチ。
select_daily_picks の後に実行する。毎回全件を計算し直す（冪等）。悪い結果もそのまま記録する。

売買の前提は推奨と同じ:
  推奨日の翌営業日の始値で買い（売り）、推奨日から hold_days 営業日後の終値で決済する
  - 買い: return_pct = 決済値 / 買値 − 1 − 手数料（往復 COST_PCT %）
  - 売り: return_pct = −(決済値 / 売値 − 1)  … 売って避けられた値下がり（プラスなら売って正解）。空売りは前提にしない

status
  pending : 推奨日の翌営業日がまだ来ていない（買付前）
  holding : 決済日前。最新の終値で途中経過を記録する（exit_date / exit_price は最新の取引日・終値）
  closed  : 決済日を過ぎ、損益が確定した
  no_data : 株価データがない（上場廃止など）

市場との比較は market_breadth.mkt_index（全銘柄の等加重指数、終値ベース）の推奨日の終値 → 決済日（または最新日）の終値。
売買は翌日始値からなので、推奨日の夜〜翌朝の市場全体の動きの分だけずれる（近似値）。

実行方法:
    cd app_works_backend
    .venv\\Scripts\\python batch\\update_pick_results.py
"""

import sys
import os
import logging
from collections import Counter
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv()

from app.database import SessionLocal
from app.models.pick_result import PickResult

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

COST_PCT = 0.1


def main() -> None:
    start = datetime.now()
    log.info("=== 推奨の実績更新バッチ 開始 ===")

    with SessionLocal() as db:
        picks = db.execute(text("""
            SELECT id, pick_date, code, side, hold_days FROM trader_schema.daily_picks
        """)).fetchall()
        if not picks:
            log.info("推奨なし")
            log.info("=== 推奨の実績更新バッチ 終了 ===")
            return
        first = min(p.pick_date for p in picks)
        prices = db.execute(text("""
            SELECT code, trade_date, open_price, current_price FROM trader_schema.stock_price
            WHERE code IN (SELECT DISTINCT code FROM trader_schema.daily_picks)
              AND trade_date >= :first AND current_price IS NOT NULL
            ORDER BY code, trade_date
        """), {"first": first}).fetchall()
        mkt = dict(db.execute(text("""
            SELECT trade_date, mkt_index FROM trader_schema.market_breadth WHERE mkt_index IS NOT NULL
        """)).fetchall())

    series: dict[str, tuple[list, list, list]] = {}
    for code, d, o, c in prices:
        s = series.setdefault(code, ([], [], []))
        s[0].append(d)
        s[1].append(float(o) if o is not None else None)
        s[2].append(float(c))
    positions = {code: {d: i for i, d in enumerate(s[0])} for code, s in series.items()}

    now = datetime.now()
    records = []
    for pick_id, pick_date, code, side, hold_days in picks:
        rec = {"pick_id": pick_id, "status": "no_data", "entry_date": None, "entry_price": None,
               "exit_date": None, "exit_price": None, "days_held": None, "return_pct": None,
               "market_return_pct": None, "excess_pct": None, "updated_at": now}
        if code not in series or pick_date not in positions[code]:
            records.append(rec)
            continue
        dates, opens, closes = series[code]
        i, last = positions[code][pick_date], len(dates) - 1
        if i + 1 > last or not opens[i + 1]:
            rec["status"] = "pending"
            records.append(rec)
            continue

        exit_i = min(i + hold_days, last)
        entry, px = opens[i + 1], closes[exit_i]
        raw = (px / entry - 1) * 100
        rec.update({
            "status":      "closed" if i + hold_days <= last else "holding",
            "entry_date":  dates[i + 1],
            "entry_price": round(entry, 1),
            "exit_date":   dates[exit_i],
            "exit_price":  round(px, 1),
            "days_held":   exit_i - i,
            "return_pct":  round(raw - COST_PCT if side == "buy" else -raw, 4),
        })
        m0, m1 = mkt.get(pick_date), mkt.get(dates[exit_i])
        if m0 and m1:
            m = (float(m1) / float(m0) - 1) * 100
            rec["market_return_pct"] = round(m, 4)
            rec["excess_pct"] = round(raw - m if side == "buy" else m - raw, 4)
        records.append(rec)

    with SessionLocal() as db:
        db.execute(text("DELETE FROM trader_schema.pick_results"))
        for i in range(0, len(records), 1000):
            db.execute(pg_insert(PickResult).values(records[i:i + 1000]))
        db.commit()

    counts = Counter(r["status"] for r in records)
    elapsed = (datetime.now() - start).total_seconds()
    log.info("完了: %d 件（%s） (%.1f 秒)", len(records), ", ".join(f"{k} {v}" for k, v in sorted(counts.items())), elapsed)
    log.info("=== 推奨の実績更新バッチ 終了 ===")


if __name__ == "__main__":
    main()
