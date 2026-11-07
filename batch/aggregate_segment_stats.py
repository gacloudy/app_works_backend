"""
signal_trades を「シグナル × 切り口」ごとに集計し、signal_segment_stats に保存するバッチ。calc_signal_trades の後に実行する。

切り口（segment_type）と、上乗せ（lift）の比較相手
  all            : 切り口なし（シグナル全体）                         … 市場平均（excess）
  industry       : 33業種                                            … 同じ日・同じ業種の全銘柄（lift_ind）
  scale          : TOPIX規模区分（Core30 / Large70 / Mid400 / Small 1 / Small 2） … 同じ規模区分（lift_scale）
  turnover       : 売買代金の5分位（1 = 小 〜 5 = 大）                 … 同じ5分位（lift_turn）
  volume         : シグナル当日の出来高比率（<1x / 1-2x / 2-3x / 3x+） … 同じ出来高比率の区分（lift_vol）
  industry_trend : 業種の勢い（strong / middle / weak）               … 同じ業種（lift_ind）
  regime         : 地合い（strong / neutral / weak）                  … 市場平均（地合いは日単位なので excess と同じ）
  scale_volume   : 規模区分 × 出来高比率（"TOPIX Core30|2-3x" など）   … 同じ規模区分（lift_scale）
  disclosure     : シグナル日以前30日以内の直近の決算・修正（"earn_revision_up" / "none" など） … 同じ業種（lift_ind）
  change         : 決算・修正の変化率の大きさ（large / small / flat。決算・修正の行のみ） … 同じ業種（lift_ind）

signal_type には、テクニカルのシグナル（signal_trades）に加えて、決算・修正（disclosure_trades の event。
"earn_revision_up" など）も含める。
  code           : 個別銘柄（件数が少ないため参考値。shrunk_lift を見る） … 同じ業種（lift_ind）

市場平均との差（avg_excess）には、業種や規模そのものの強弱（例: この2年の銀行株の強さ）が混ざる。
シグナル本来の効果を見るため、t 値・探索/検証期間・validated は上乗せ（lift）で計算する。

集計値
  avg_net_return / win_rate : 手数料（往復 COST_PCT %）を差し引いた1回あたりの損益と、プラスだった割合
  avg_excess                : 市場平均との差（参考）
  avg_lift / t_stat         : 上乗せと、日付ごとの平均を1サンプルとした t 値
  train_* / test_*          : シグナル日が TRAIN_END 以前（探索期間）と以降（検証期間）に分けた上乗せと t 値
  validated                 : 探索期間で |t| >= T_TRAIN、かつ検証期間でも同じ向きで |t| >= T_TEST のもの。
                              切り口の組み合わせが多く、探索期間だけでは偶然よく見えるものが混ざるため、
                              検証期間でも成り立ったものだけを「使えるサイン」とする（銘柄別は件数不足のため対象外）
  shrunk_lift               : 業種・銘柄別の上乗せを、同じシグナル全体の上乗せへ日付数に応じて寄せた推定値

N 日後のリターンは隣接日どうしで重なるため、t 値は N が大きいほど過大になりやすい。

実行方法:
    cd app_works_backend
    .venv\\Scripts\\python batch\\aggregate_segment_stats.py
"""

import sys
import os
import logging
from datetime import date, datetime

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv()

from app.database import SessionLocal
from app.models.signal_segment_stats import SignalSegmentStats
from batch.aggregate_stats import dec

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PERIODS = [5, 10, 20]
COST_PCT = 0.1                 # 往復の売買手数料・スリッページ（%）
TRAIN_END = date(2025, 12, 31)  # 探索期間の最終日。翌日以降を検証期間とする
MIN_SAMPLES = 100              # 切り口ごとに必要なシグナル数（銘柄別は MIN_CODE_SAMPLES）
MIN_DATES = 30
MIN_CODE_SAMPLES = 5
MIN_TRAIN_DATES = 20
MIN_TEST_DATES = 10
T_TRAIN = 3.0                  # 探索期間で必要な |t|（多数の切り口を試すため厳しめ）
T_TEST = 1.65                  # 検証期間で必要な |t|（同じ向きであることを確かめる片側5%）
PRIOR_DATES = 20               # 縮小推定で全体の値に与える重み（日付数換算）
# 切り口ごとの上乗せの比較相手（signal_trades の列名の接頭辞）
LIFT_PREFIX = {
    "all": "excess", "regime": "excess",
    "industry": "lift_ind", "industry_trend": "lift_ind", "code": "lift_ind",
    "scale": "lift_scale", "scale_volume": "lift_scale",
    "turnover": "lift_turn", "volume": "lift_vol",
    "disclosure": "lift_ind", "change": "lift_ind",
}
SEGMENTS = ["industry", "scale", "turnover", "volume", "industry_trend", "regime", "scale_volume", "disclosure",
            "change", "code"]
SHRUNK_SEGMENTS = {"industry", "code"}
STAT_COLS = [
    "sample_count", "date_count", "avg_net_return", "win_rate", "avg_excess", "excess_win_rate",
    "avg_lift", "lift_win_rate", "t_stat",
    "train_count", "train_lift", "train_t", "test_count", "test_lift", "test_t", "validated", "shrunk_lift",
]


def date_t_stat(df: pd.DataFrame, col: str) -> tuple[float | None, int]:
    """日付ごとの平均を1サンプルとした t 値と日付数。"""
    by_date = df.groupby("signal_date")[col].mean().dropna()
    n = len(by_date)
    if n < 2 or by_date.std() == 0:
        return None, n
    return float(by_date.mean() / (by_date.std() / np.sqrt(n))), n


def calc(df: pd.DataFrame, period: int, lift_prefix: str, min_samples: int) -> dict | None:
    ret_col, x_col, l_col = f"ret_{period}d", f"excess_{period}d", f"{lift_prefix}_{period}d"
    df = df.dropna(subset=[ret_col, x_col, l_col])
    if len(df) < min_samples:
        return None
    net = df[ret_col] - COST_PCT
    t, dates = date_t_stat(df, l_col)
    stats = {
        "sample_count":    len(df),
        "date_count":      dates,
        "avg_net_return":  dec(net.mean()),
        "win_rate":        dec((net > 0).mean() * 100, 2),
        "avg_excess":      dec(df[x_col].mean()),
        "excess_win_rate": dec((df[x_col] > 0).mean() * 100, 2),
        "avg_lift":        dec(df[l_col].mean()),
        "lift_win_rate":   dec((df[l_col] > 0).mean() * 100, 2),
        "t_stat":          dec(t, 3) if t is not None else None,
    }

    train, test = df[df["signal_date"] <= TRAIN_END], df[df["signal_date"] > TRAIN_END]
    train_t, train_dates = date_t_stat(train, l_col)
    test_t, test_dates = date_t_stat(test, l_col)
    stats.update({
        "train_count": len(train),
        "train_lift":  dec(train[l_col].mean()) if len(train) else None,
        "train_t":     dec(train_t, 3) if train_t is not None else None,
        "test_count":  len(test),
        "test_lift":   dec(test[l_col].mean()) if len(test) else None,
        "test_t":      dec(test_t, 3) if test_t is not None else None,
    })
    stats["validated"] = bool(
        len(df) >= MIN_SAMPLES and dates >= MIN_DATES
        and train_dates >= MIN_TRAIN_DATES and test_dates >= MIN_TEST_DATES
        and train_t is not None and test_t is not None
        and abs(train_t) >= T_TRAIN
        and np.sign(test_t) == np.sign(train_t) and abs(test_t) >= T_TEST
    )
    return stats


def main() -> None:
    start = datetime.now()
    log.info("=== シグナル切り口別集計バッチ 開始 ===")

    value_cols = [f"{p}_{n}d" for p in ["ret", "excess", "lift_ind", "lift_scale", "lift_turn", "lift_vol"]
                  for n in PERIODS]
    disc_value_cols = [c for c in value_cols if not c.startswith("lift_vol")]
    with SessionLocal() as db:
        signal_trades = pd.read_sql(text(f"""
            SELECT code, signal_date, signal_type, industry, scale, turnover_q, volume_bucket, industry_trend, regime,
                   recent_disclosure AS disclosure, {", ".join(value_cols)}
            FROM trader_schema.signal_trades
        """), db.connection())
        # 決算・修正もシグナルの一種（signal_type = "earn_revision_up" など）として同じ方法で集計する
        disclosure_trades = pd.read_sql(text(f"""
            SELECT code, base_date AS signal_date, event AS signal_type, industry, scale, turnover_q, industry_trend,
                   regime, change_bucket AS change, {", ".join(disc_value_cols)}
            FROM trader_schema.disclosure_trades
        """), db.connection())
    trades = pd.concat([signal_trades, disclosure_trades], ignore_index=True)
    if trades.empty:
        log.info("signal_trades が空です（先に calc_signal_trades を実行してください）")
        log.info("=== シグナル切り口別集計バッチ 終了 ===")
        return
    log.info("取引: シグナル %d 件 / 決算・修正 %d 件", len(signal_trades), len(disclosure_trades))

    for c in value_cols:
        trades[c] = trades[c].astype(float)
    trades["signal_date"] = pd.to_datetime(trades["signal_date"]).dt.date
    trades["turnover"] = trades["turnover_q"].map(lambda q: str(int(q)) if not pd.isna(q) else None)
    trades["volume"] = trades["volume_bucket"]
    trades["scale_volume"] = [
        f"{s}|{v}" if isinstance(s, str) and isinstance(v, str) else None
        for s, v in zip(trades["scale"], trades["volume_bucket"])
    ]

    records: list[dict] = []
    now = datetime.now()
    for signal_type, df_sig in trades.groupby("signal_type"):
        for period in PERIODS:
            base = calc(df_sig, period, LIFT_PREFIX["all"], MIN_SAMPLES)
            if base is None:
                continue
            base["shrunk_lift"] = base["avg_lift"]
            records.append({"signal_type": signal_type, "segment_type": "all", "segment_value": "",
                            "period": period, **base})

            for seg in SEGMENTS:
                prefix = LIFT_PREFIX[seg]
                min_samples = MIN_CODE_SAMPLES if seg == "code" else MIN_SAMPLES
                # 縮小推定の寄せ先: 同じシグナル全体の、同じ比較相手での上乗せ
                overall = df_sig[f"{prefix}_{period}d"].mean()
                for value, grp in df_sig.dropna(subset=[seg]).groupby(seg):
                    stats = calc(grp, period, prefix, min_samples)
                    if stats is None:
                        continue
                    if seg == "code":
                        stats["validated"] = False
                    stats["shrunk_lift"] = None
                    if seg in SHRUNK_SEGMENTS and stats["avg_lift"] is not None and not np.isnan(overall):
                        d = stats["date_count"]
                        stats["shrunk_lift"] = dec(
                            (d * float(stats["avg_lift"]) + PRIOR_DATES * overall) / (d + PRIOR_DATES)
                        )
                    records.append({"signal_type": signal_type, "segment_type": seg, "segment_value": str(value),
                                    "period": period, **stats})

    records = [{**{c: r.get(c) for c in ["signal_type", "segment_type", "segment_value", "period", *STAT_COLS]},
                "updated_at": now} for r in records]
    validated = sum(1 for r in records if r["validated"])
    log.info("集計: %d 件（うち検証期間でも成り立ったもの %d 件）", len(records), validated)

    with SessionLocal() as db:
        for i in range(0, len(records), 1000):
            stmt = pg_insert(SignalSegmentStats).values(records[i:i + 1000])
            stmt = stmt.on_conflict_do_update(
                constraint="uq_signal_segment_stats",
                set_={c: stmt.excluded[c] for c in [*STAT_COLS, "updated_at"]},
            )
            db.execute(stmt)
        deleted = db.execute(
            text("DELETE FROM trader_schema.signal_segment_stats WHERE updated_at < :now"), {"now": now}
        ).rowcount
        db.commit()

    elapsed = (datetime.now() - start).total_seconds()
    log.info("完了: %d 件保存、%d 件削除 (%.1f 秒)", len(records), deleted, elapsed)
    log.info("=== シグナル切り口別集計バッチ 終了 ===")


if __name__ == "__main__":
    main()
