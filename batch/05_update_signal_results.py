"""
signal_history テーブルのリターン列（return_3d/5d/10d/20d）を埋めるバッチ。

シグナル発生日から N 取引日後の株価を取得し、リターン（%）を計算して更新する。
N 取引日 = stock_price に実際に存在する取引日を N 件カウントしたもの。

実行方法:
    cd app_works_backend
    .venv\\Scripts\\python batch\\05_update_signal_results.py
"""

import sys
import os
import logging
from datetime import datetime
from decimal import Decimal

from dotenv import load_dotenv
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv()

from app.database import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PERIODS = [3, 5, 10, 20]


def main() -> None:
    start = datetime.now()
    log.info("=== シグナル結果更新バッチ 開始 ===")

    # return_Nd が1つでも NULL の未処理シグナルを取得
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT id, code, signal_date, price_at_signal,
                   return_3d, return_5d, return_10d, return_20d
            FROM trader_schema.signal_history
            WHERE (return_3d IS NULL OR return_5d IS NULL
                   OR return_10d IS NULL OR return_20d IS NULL)
              AND price_at_signal IS NOT NULL
        """)).fetchall()

    if not rows:
        log.info("更新対象なし")
        log.info("=== シグナル結果更新バッチ 終了 ===")
        return

    log.info("更新対象: %d 件", len(rows))
    updated = 0

    with SessionLocal() as db:
        for row in rows:
            sig_id       = row[0]
            code         = row[1]
            signal_date  = row[2]
            price_base   = float(row[3])
            cur_returns  = {3: row[4], 5: row[5], 10: row[6], 20: row[7]}

            updates: dict[str, Decimal] = {}
            for n in PERIODS:
                col = f"return_{n}d"
                if cur_returns[n] is not None:
                    continue  # すでに値あり

                # signal_date より後の N 番目の取引日の株価を取得
                price_n = db.execute(text("""
                    SELECT current_price
                    FROM (
                        SELECT current_price,
                               ROW_NUMBER() OVER (ORDER BY trade_date) AS rn
                        FROM trader_schema.stock_price
                        WHERE code = :code
                          AND trade_date > :signal_date
                          AND current_price IS NOT NULL
                    ) t
                    WHERE rn = :n
                """), {"code": code, "signal_date": signal_date, "n": n}).scalar()

                if price_n is not None:
                    ret = (float(price_n) - price_base) / price_base * 100
                    updates[col] = Decimal(str(round(ret, 4)))

            if updates:
                set_clause = ", ".join(f"{k} = :{k}" for k in updates)
                db.execute(
                    text(f"UPDATE trader_schema.signal_history SET {set_clause} WHERE id = :id"),
                    {**{k: float(v) for k, v in updates.items()}, "id": sig_id},
                )
                updated += 1

        db.commit()

    elapsed = (datetime.now() - start).total_seconds()
    log.info("完了: %d 件更新 (%.1f 秒)", updated, elapsed)
    log.info("=== シグナル結果更新バッチ 終了 ===")


if __name__ == "__main__":
    main()
