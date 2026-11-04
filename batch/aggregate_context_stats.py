"""
地合い・業種の強弱を使った検証結果を集計するバッチ。calc_market_context と aggregate_stats の後に実行する。

signal_context_stats
  シグナル発生日の「状況」でシグナルを分け、市場超過リターンを aggregate_stats と同じ方法で集計する。
    context_type = "regime"         : その日の地合い（market_breadth.regime: strong / neutral / weak）
    context_type = "industry_trend" : その銘柄の業種の過去20日の強さ（industry_daily.rank_20d の上位1/3 = strong、
                                      下位1/3 = weak、それ以外 = middle）
  同じシグナルでも、地合いや業種の勢いによって効き方が変わるかを見るためのもの。

industry_momentum_stats
  「直近で強い（弱い）業種は、その後も市場に勝ち続けるか」を検証する。
  取引日ごとに過去 lookback 日の業種超過リターンで順位をつけ、上位 TOP_N 業種（top）・下位 TOP_N 業種（bottom）の
  その後 horizon 日の市場超過リターンを日付ごとに平均し、日付単位で集計する。spread = top − bottom。
    win_rate : 日付単位の値がプラスだった日の割合（%）
    t_stat   : 日付単位の値の t 値（horizon 日のリターンは隣接日どうしで重なるため、horizon が大きいほど過大になりやすい）
    前半/後半: 判定日の中央日で2分割した平均と、符号の一致（is_consistent）

実行方法:
    cd app_works_backend
    .venv\\Scripts\\python batch\\aggregate_context_stats.py
"""

import sys
import os
import logging
from datetime import datetime

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv()

from app.database import SessionLocal
from app.models.industry_momentum_stats import IndustryMomentumStats
from app.models.signal_context_stats import SignalContextStats
from batch.aggregate_stats import PERIODS, calc_stats, dec
from batch.signal_skip_util import load_skip_windows, skipped_mask

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

LOOKBACKS = [5, 20]
HORIZONS = [5, 20]
TOP_N = 5               # 業種モメンタムで上位・下位として扱う業種数
MIN_HALF_DATES = 3      # 前半/後半それぞれに必要な日付数
CONTEXT_COLS = [
    "sample_count", "date_count", "excess_win_rate", "avg_excess", "median_excess",
    "t_stat", "first_half_excess", "second_half_excess", "is_consistent",
]
MOMENTUM_COLS = [
    "date_count", "avg_excess", "win_rate", "t_stat",
    "first_half_excess", "second_half_excess", "is_consistent",
]


def industry_trend_of(rank: float, ranked_count: float) -> str | None:
    """業種の順位（1 = 最も強い）を strong / middle / weak に分ける。"""
    if pd.isna(rank) or pd.isna(ranked_count) or ranked_count == 0:
        return None
    if rank <= ranked_count / 3:
        return "strong"
    if rank > ranked_count * 2 / 3:
        return "weak"
    return "middle"


def calc_signal_context_stats(signals: pd.DataFrame, regimes: pd.Series, industries: pd.DataFrame) -> list[dict]:
    """シグナルを発生日の地合い・業種の強さで分けて集計する。

    signals    : signal_type, code, signal_date, industry と return/mkt_excess/ind_excess 列
    regimes    : trade_date → regime
    industries : trade_date, industry, rank_20d
    """
    ranked_count = industries.groupby("trade_date")["rank_20d"].count().rename("ranked_count")
    ind = industries.join(ranked_count, on="trade_date")
    ind["industry_trend"] = [industry_trend_of(r, n) for r, n in zip(ind["rank_20d"], ind["ranked_count"])]

    df = signals.copy()
    df["regime"] = df["signal_date"].map(regimes)
    df = df.merge(
        ind[["trade_date", "industry", "industry_trend"]],
        left_on=["signal_date", "industry"], right_on=["trade_date", "industry"], how="left",
    ).drop(columns="trade_date")

    # 前半/後半の境界は aggregate_stats と同じく全シグナル共通にする
    dates = np.sort(df["signal_date"].unique())
    mid_date = dates[max(len(dates) // 2 - 1, 0)]

    records = []
    for context_type in ["regime", "industry_trend"]:
        for (signal_type, context_value), grp in df.dropna(subset=[context_type]).groupby(["signal_type", context_type]):
            for period in PERIODS:
                stats = calc_stats(grp, period, mid_date)
                if not stats or stats.get("avg_excess") is None:
                    continue
                records.append({
                    "signal_type":   signal_type,
                    "context_type":  context_type,
                    "context_value": context_value,
                    "period":        period,
                    **{c: stats.get(c) for c in CONTEXT_COLS},
                })
    return records


def summarize_by_date(by_date: pd.Series, mid_date) -> dict:
    """日付ごとの値（Series, index = 日付）を集計する。"""
    by_date = by_date.dropna()
    n = len(by_date)
    if n == 0:
        return {}
    stats = {
        "date_count": n,
        "avg_excess": dec(by_date.mean()),
        "win_rate":   dec((by_date > 0).mean() * 100, 2),
    }
    if n >= 2 and by_date.std() > 0:
        stats["t_stat"] = dec(by_date.mean() / (by_date.std() / np.sqrt(n)), 3)

    first, second = by_date[by_date.index <= mid_date], by_date[by_date.index > mid_date]
    first_avg = first.mean() if len(first) >= MIN_HALF_DATES else None
    second_avg = second.mean() if len(second) >= MIN_HALF_DATES else None
    stats["first_half_excess"] = dec(first_avg)
    stats["second_half_excess"] = dec(second_avg)
    if first_avg is not None and second_avg is not None:
        stats["is_consistent"] = bool(np.sign(first_avg) == np.sign(second_avg) == np.sign(by_date.mean()) != 0)
    return stats


def calc_industry_momentum_stats(industries: pd.DataFrame, mkt_index: pd.Series) -> list[dict]:
    """過去の業種の強弱で上位・下位に分け、その後の業種超過リターンを集計する。

    industries : trade_date, industry, index_value, excess_5d, excess_20d, member_count, rank_5d, rank_20d
    mkt_index  : trade_date → 市場指数
    """
    ind = industries.sort_values(["industry", "trade_date"]).copy()
    mkt = mkt_index.sort_index()
    for h in HORIZONS:
        fwd = ind.groupby("industry")["index_value"].shift(-h) / ind["index_value"] - 1
        mkt_fwd = mkt.shift(-h) / mkt - 1
        ind[f"fwd_{h}d"] = (fwd - ind["trade_date"].map(mkt_fwd)) * 100

    records = []
    for lb in LOOKBACKS:
        rank_col = f"rank_{lb}d"
        ranked = ind.dropna(subset=[rank_col])
        n_ranked = ranked.groupby("trade_date")[rank_col].transform("count")
        top = ranked[ranked[rank_col] <= TOP_N]
        bottom = ranked[ranked[rank_col] > n_ranked - TOP_N]
        for h in HORIZONS:
            col = f"fwd_{h}d"
            top_by_date = top.groupby("trade_date")[col].mean()
            bottom_by_date = bottom.groupby("trade_date")[col].mean()
            spread_by_date = (top_by_date - bottom_by_date).dropna()
            if spread_by_date.empty:
                continue
            dates = np.sort(spread_by_date.index.unique())
            mid_date = dates[max(len(dates) // 2 - 1, 0)]
            for bucket, by_date in [("top", top_by_date), ("bottom", bottom_by_date), ("spread", spread_by_date)]:
                stats = summarize_by_date(by_date, mid_date)
                if not stats:
                    continue
                records.append({
                    "lookback": lb,
                    "horizon":  h,
                    "bucket":   bucket,
                    **{c: stats.get(c) for c in MOMENTUM_COLS},
                })
    return records


def load_inputs(db) -> tuple[pd.DataFrame, pd.Series, pd.Series, pd.DataFrame]:
    ret_cols = [f"{p}_{n}d" for p in ["return", "mkt_excess", "ind_excess"] for n in PERIODS]
    sig_rows = db.execute(text(f"""
        SELECT sh.signal_type, sh.code, sh.signal_date, sm.industry, {", ".join("sh." + c for c in ret_cols)}
        FROM trader_schema.signal_history sh
        JOIN trader_schema.stock_master sm ON sh.code = sm.code
        WHERE sh.return_3d IS NOT NULL
    """)).fetchall()
    breadth_rows = db.execute(text("""
        SELECT trade_date, regime, mkt_index FROM trader_schema.market_breadth
    """)).fetchall()
    ind_rows = db.execute(text("""
        SELECT trade_date, industry, member_count, index_value, rank_5d, rank_20d
        FROM trader_schema.industry_daily
    """)).fetchall()
    skip_windows = load_skip_windows(db)

    signals = pd.DataFrame(sig_rows, columns=["signal_type", "code", "signal_date", "industry", *ret_cols])
    for col in ret_cols:
        signals[col] = signals[col].astype(float)
    skipped = skipped_mask(signals, skip_windows, "signal_date")
    log.info("集計対象シグナル: %d 件（除外期間のため %d 件を除外）", int((~skipped).sum()), int(skipped.sum()))
    signals = signals[~skipped]

    breadth = pd.DataFrame(breadth_rows, columns=["trade_date", "regime", "mkt_index"]).set_index("trade_date")
    industries = pd.DataFrame(ind_rows, columns=["trade_date", "industry", "member_count", "index_value", "rank_5d", "rank_20d"])
    industries["index_value"] = industries["index_value"].astype(float)
    for col in ["rank_5d", "rank_20d"]:
        industries[col] = industries[col].astype(float)
    return signals, breadth["regime"], breadth["mkt_index"].astype(float), industries


def save(db, model, records: list[dict], constraint: str, key_cols: list[str], now: datetime) -> int:
    """upsert し、今回の集計に含まれなかった古い行を削除する。削除件数を返す。"""
    for r in records:
        r["updated_at"] = now
    for i in range(0, len(records), 500):
        stmt = pg_insert(model).values(records[i:i + 500])
        stmt = stmt.on_conflict_do_update(
            constraint=constraint,
            set_={c: stmt.excluded[c] for c in records[0] if c not in key_cols},
        )
        db.execute(stmt)
    return db.execute(
        text(f"DELETE FROM trader_schema.{model.__tablename__} WHERE updated_at < :now"), {"now": now}
    ).rowcount


def main() -> None:
    start = datetime.now()
    log.info("=== 地合い・業種の検証集計バッチ 開始 ===")

    with SessionLocal() as db:
        signals, regimes, mkt_index, industries = load_inputs(db)
    if industries.empty:
        log.info("industry_daily が空です（先に calc_market_context を実行してください）")
        log.info("=== 地合い・業種の検証集計バッチ 終了 ===")
        return

    context_records = calc_signal_context_stats(signals, regimes, industries) if not signals.empty else []
    momentum_records = calc_industry_momentum_stats(industries, mkt_index)
    log.info("集計: signal_context_stats %d 件 / industry_momentum_stats %d 件", len(context_records), len(momentum_records))

    now = datetime.now()
    with SessionLocal() as db:
        deleted = 0
        if context_records:
            deleted += save(db, SignalContextStats, context_records, "uq_signal_context_stats",
                            ["signal_type", "context_type", "context_value", "period"], now)
        if momentum_records:
            deleted += save(db, IndustryMomentumStats, momentum_records, "uq_industry_momentum_stats",
                            ["lookback", "horizon", "bucket"], now)
        db.commit()

    elapsed = (datetime.now() - start).total_seconds()
    log.info("完了: %d 件保存、%d 件削除 (%.1f 秒)", len(context_records) + len(momentum_records), deleted, elapsed)
    log.info("=== 地合い・業種の検証集計バッチ 終了 ===")


if __name__ == "__main__":
    main()
