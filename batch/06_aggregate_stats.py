"""
signal_history の結果を集計し、signal_stats テーブルを更新するバッチ。

全業種合計 と 業種別 の勝率・平均リターン・中央値・標準偏差を計算する。
サンプル数が MIN_SAMPLES 未満のものは除外する。

実行方法:
    cd app_works_backend
    .venv\\Scripts\\python batch\\06_aggregate_stats.py
"""

import sys
import os
import logging
from datetime import datetime
from decimal import Decimal

import pandas as pd
import numpy as np
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv()

from app.database import SessionLocal
from app.models.signal_stats import SignalStats

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

MIN_SAMPLES = 10
PERIODS = [3, 5, 10, 20]


def calc_stats(returns: pd.Series) -> dict:
    returns = returns.dropna()
    n = len(returns)
    if n < MIN_SAMPLES:
        return {}
    return {
        "sample_count":  n,
        "win_rate":      Decimal(str(round(float((returns > 0).mean() * 100), 2))),
        "avg_return":    Decimal(str(round(float(returns.mean()), 4))),
        "median_return": Decimal(str(round(float(returns.median()), 4))),
        "std_return":    Decimal(str(round(float(returns.std()), 4))),
    }


def main() -> None:
    start = datetime.now()
    log.info("=== 統計集計バッチ 開始 ===")

    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT sh.signal_type, sm.industry,
                   sh.return_3d, sh.return_5d, sh.return_10d, sh.return_20d
            FROM trader_schema.signal_history sh
            JOIN trader_schema.stock_master sm ON sh.code = sm.code
            WHERE sh.return_5d IS NOT NULL
        """)).fetchall()

    if not rows:
        log.info("集計対象データなし")
        log.info("=== 統計集計バッチ 終了 ===")
        return

    df = pd.DataFrame(rows, columns=["signal_type", "industry", "return_3d", "return_5d", "return_10d", "return_20d"])
    for col in ["return_3d", "return_5d", "return_10d", "return_20d"]:
        df[col] = df[col].astype(float)

    log.info("集計対象シグナル: %d 件", len(df))

    records: list[dict] = []
    now = datetime.now()

    for signal_type in df["signal_type"].unique():
        df_sig = df[df["signal_type"] == signal_type]

        for period in PERIODS:
            col = f"return_{period}d"
            if col not in df_sig.columns:
                continue

            # 全業種合計
            stats = calc_stats(df_sig[col])
            if stats:
                records.append({
                    "signal_type": signal_type,
                    "industry":    "",
                    "period":      period,
                    "updated_at":  now,
                    **stats,
                })

            # 業種別
            for industry, df_ind in df_sig.groupby("industry"):
                stats = calc_stats(df_ind[col])
                if stats:
                    records.append({
                        "signal_type": signal_type,
                        "industry":    str(industry),
                        "period":      period,
                        "updated_at":  now,
                        **stats,
                    })

    log.info("集計レコード: %d 件 → DB保存中...", len(records))

    if not records:
        log.info("保存対象なし（サンプル数不足）")
        log.info("=== 統計集計バッチ 終了 ===")
        return

    with SessionLocal() as db:
        stmt = pg_insert(SignalStats).values(records)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_stats_type_industry_period",
            set_={c: stmt.excluded[c] for c in [
                "sample_count", "win_rate", "avg_return", "median_return", "std_return", "updated_at"
            ]},
        )
        db.execute(stmt)
        db.commit()

    elapsed = (datetime.now() - start).total_seconds()
    log.info("完了: %d 件保存 (%.1f 秒)", len(records), elapsed)
    log.info("=== 統計集計バッチ 終了 ===")


if __name__ == "__main__":
    main()
