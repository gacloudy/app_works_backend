"""
signal_history の結果を集計し、signal_stats テーブルを更新するバッチ。

全業種合計 と 業種別 に以下を計算する。
  生リターン      : 勝率・平均・中央値・標準偏差（従来どおり）
  市場超過リターン: 勝率・平均・中央値、同業種平均との差
  t_stat          : 同じ日に出たシグナルを1件にまとめ（日付ごとの平均）、日付間のばらつきから算出した t 値
                    ※ 期間 N 日のリターンは隣接日どうしで重なるため、N が大きいほど t 値は過大になりやすい
  前半/後半       : シグナル日の中央日で2分割した各期間の平均超過リターンと、符号の一致（is_consistent）
  shrunk_excess   : 業種別の平均超過リターンを全業種平均へ寄せた推定値
                    = (業種の日付数 × 業種平均 + PRIOR_DATES × 全業種平均) / (業種の日付数 + PRIOR_DATES)

signal_skip の除外期間（分割・極端な値動き）に入るシグナルは集計しない。
サンプル数が MIN_SAMPLES 未満、または発生日数が MIN_DATES 未満のものは除外する。

実行方法:
    cd app_works_backend
    .venv\\Scripts\\python batch\\aggregate_stats.py
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
from batch.signal_skip_util import load_skip_windows, skipped_mask

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

MIN_SAMPLES = 10
MIN_DATES = 5
MIN_HALF_DATES = 3  # 前半/後半それぞれに必要な発生日数
PRIOR_DATES = 20    # 縮小推定で全業種平均に与える重み（日付数換算）
PERIODS = [3, 5, 10, 20]
STAT_COLS = [
    "sample_count", "win_rate", "avg_return", "median_return", "std_return",
    "date_count", "excess_win_rate", "avg_excess", "median_excess", "avg_ind_excess",
    "t_stat", "first_half_excess", "second_half_excess", "is_consistent", "shrunk_excess",
]


def dec(v: float | None, digits: int = 4) -> Decimal | None:
    if v is None or np.isnan(v):
        return None
    return Decimal(str(round(float(v), digits)))


def date_mean(df: pd.DataFrame, col: str) -> pd.Series:
    """日付ごとの平均（同日に出たシグナルを1サンプルにまとめる）。"""
    return df.groupby("signal_date")[col].mean().dropna()


def calc_stats(df: pd.DataFrame, period: int, mid_date) -> dict:
    raw_col, x_col, i_col = f"return_{period}d", f"mkt_excess_{period}d", f"ind_excess_{period}d"
    df = df.dropna(subset=[raw_col])
    n = len(df)
    if n < MIN_SAMPLES:
        return {}

    raw = df[raw_col]
    stats = {
        "sample_count":  n,
        "win_rate":      dec((raw > 0).mean() * 100, 2),
        "avg_return":    dec(raw.mean()),
        "median_return": dec(raw.median()),
        "std_return":    dec(raw.std()),
    }

    dx = df.dropna(subset=[x_col])
    by_date = date_mean(dx, x_col)
    stats["date_count"] = int(df["signal_date"].nunique())
    if stats["date_count"] < MIN_DATES:
        return {}
    if dx.empty:
        return stats

    x = dx[x_col]
    stats["excess_win_rate"] = dec((x > 0).mean() * 100, 2)
    stats["avg_excess"] = dec(x.mean())
    stats["median_excess"] = dec(x.median())
    stats["avg_ind_excess"] = dec(dx[i_col].mean())
    if len(by_date) >= MIN_DATES and by_date.std() > 0:
        stats["t_stat"] = dec(by_date.mean() / (by_date.std() / np.sqrt(len(by_date))), 3)

    first, second = by_date[by_date.index <= mid_date], by_date[by_date.index > mid_date]
    first_avg = dx[dx["signal_date"] <= mid_date][x_col].mean() if len(first) >= MIN_HALF_DATES else None
    second_avg = dx[dx["signal_date"] > mid_date][x_col].mean() if len(second) >= MIN_HALF_DATES else None
    stats["first_half_excess"] = dec(first_avg)
    stats["second_half_excess"] = dec(second_avg)
    if first_avg is not None and second_avg is not None:
        stats["is_consistent"] = bool(np.sign(first_avg) == np.sign(second_avg) == np.sign(x.mean()) != 0)
    return stats


def main() -> None:
    start = datetime.now()
    log.info("=== 統計集計バッチ 開始 ===")

    ret_cols = [f"{p}_{n}d" for p in ["return", "mkt_excess", "ind_excess"] for n in PERIODS]
    with SessionLocal() as db:
        rows = db.execute(text(f"""
            SELECT sh.signal_type, sh.code, sh.signal_date, sm.industry, {", ".join("sh." + c for c in ret_cols)}
            FROM trader_schema.signal_history sh
            JOIN trader_schema.stock_master sm ON sh.code = sm.code
            WHERE sh.return_3d IS NOT NULL
        """)).fetchall()
        skip_windows = load_skip_windows(db)

    if not rows:
        log.info("集計対象データなし")
        log.info("=== 統計集計バッチ 終了 ===")
        return

    df = pd.DataFrame(rows, columns=["signal_type", "code", "signal_date", "industry", *ret_cols])
    for col in ret_cols:
        df[col] = df[col].astype(float)

    skipped = skipped_mask(df, skip_windows, "signal_date")
    log.info("集計対象シグナル: %d 件（除外期間のため %d 件を除外）", int((~skipped).sum()), int(skipped.sum()))
    df = df[~skipped]
    if df.empty:
        log.info("=== 統計集計バッチ 終了 ===")
        return

    # 前半/後半の境界はシグナル種別によらず共通にする
    dates = np.sort(df["signal_date"].unique())
    mid_date = dates[max(len(dates) // 2 - 1, 0)]

    records: list[dict] = []
    now = datetime.now()

    for signal_type in df["signal_type"].unique():
        df_sig = df[df["signal_type"] == signal_type]

        for period in PERIODS:
            # 全業種合計
            stats_all = calc_stats(df_sig, period, mid_date)
            if not stats_all:
                continue
            stats_all["shrunk_excess"] = stats_all.get("avg_excess")
            records.append({
                "signal_type": signal_type,
                "industry":    "",
                "period":      period,
                "updated_at":  now,
                **stats_all,
            })

            # 業種別
            all_excess = stats_all.get("avg_excess")
            for industry, df_ind in df_sig.groupby("industry"):
                stats = calc_stats(df_ind, period, mid_date)
                if not stats:
                    continue
                if stats.get("avg_excess") is not None and all_excess is not None:
                    d = stats["date_count"]
                    stats["shrunk_excess"] = dec(
                        (d * float(stats["avg_excess"]) + PRIOR_DATES * float(all_excess)) / (d + PRIOR_DATES)
                    )
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

    # 列を揃える（超過リターンが計算できなかった行は NULL）
    records = [{c: r.get(c) for c in ["signal_type", "industry", "period", "updated_at", *STAT_COLS]} for r in records]

    with SessionLocal() as db:
        for i in range(0, len(records), 500):
            stmt = pg_insert(SignalStats).values(records[i:i + 500])
            stmt = stmt.on_conflict_do_update(
                constraint="uq_stats_type_industry_period",
                set_={c: stmt.excluded[c] for c in [*STAT_COLS, "updated_at"]},
            )
            db.execute(stmt)
        # 今回の集計で条件を満たさなくなった組み合わせは削除する
        deleted = db.execute(
            text("DELETE FROM trader_schema.signal_stats WHERE updated_at < :now"), {"now": now}
        ).rowcount
        db.commit()

    elapsed = (datetime.now() - start).total_seconds()
    log.info("完了: %d 件保存、%d 件削除 (%.1f 秒)", len(records), deleted, elapsed)
    log.info("=== 統計集計バッチ 終了 ===")


if __name__ == "__main__":
    main()
