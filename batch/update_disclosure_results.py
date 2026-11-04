"""
fin_disclosure の各開示を分類し、開示後の株価の反応（市場超過リターン）を計算するバッチ。
fetch_fin_disclosures と calc_market_context の後に実行する。毎回全件を計算し直す（冪等）。

分類（event_type）と比較方法（base_value → new_value）
  earn_revision : 業績予想の修正。同じ事業年度の直前の予想 → 修正後の予想
  div_revision  : 配当予想の修正。同じ事業年度の直前の年間配当予想 → 修正後の年間配当予想
  q_results     : 四半期決算短信。同じ事業年度の直前の予想 → 決算短信に載った予想（据え置きなら flat）
  fy_results    : 通期決算短信。当期の実績 → 翌期の予想（会社の来期見通し）
  利益は営業利益 → 経常利益 → 純利益の順に、比較元・比較先の両方に値がある項目を使う。
  direction は change_pct が +FLAT_PCT 超なら up、−FLAT_PCT 未満なら down、それ以外は flat。
  「直前の予想」は fin_disclosure に保存済みの開示から探すため、過去分を取り込んでいないと NULL になる。

株価の反応
  reaction_date   : 開示を株価が反映できる最初の取引日（15:30 より前の開示は当日、以降は翌取引日）
  reaction_excess : 反応日の前の取引日の終値 → 反応日の終値 のリターン − 同期間の市場リターン（%）
  drift_5d / 20d  : 反応日の終値 → N 取引日後の終値 のリターン − 同期間の市場リターン（%）
                    反応日の終値で買った場合に、その後も同じ方向に動き続けたか（ドリフト）を見る。
  市場リターンは market_breadth.mkt_index（全銘柄の等加重指数）を使う。
  株式分割・前日終値の不一致の除外期間（signal_skip）にかかる開示は、株価が不連続なため計算しない。
  極端な値動き（extreme_move）は開示への反応そのものである可能性が高いため除外しない。

実行方法:
    cd app_works_backend
    .venv\\Scripts\\python batch\\update_disclosure_results.py
"""

import sys
import os
import bisect
import logging
from datetime import date, datetime

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv()

from app.database import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

MARKET_CLOSE = "15:30"
FLAT_PCT = 0.5
MAX_CHANGE_PCT = 99999.0
DRIFT_DAYS = [5, 20]
PROFIT_METRICS = ["op", "odp", "np"]
SKIP_REASONS = ("split_suspected", "price_mismatch")
RESULT_COLS = [
    "event_type", "metric", "base_value", "new_value", "change_pct", "direction",
    "reaction_date", "reaction_excess", "drift_5d", "drift_20d",
]


def event_type_of(doc_type: str) -> str | None:
    if doc_type.startswith("REIT"):
        return None
    if doc_type == "EarnForecastRevision":
        return "earn_revision"
    if doc_type == "DividendForecastRevision":
        return "div_revision"
    if doc_type.startswith("FYFinancialStatements"):
        return "fy_results"
    if "FinancialStatements" in doc_type:
        return "q_results"
    return None


def forecast_for_fy(row, fy_en: date, metric: str) -> float | None:
    """開示 row に載っている、fy_en に終わる事業年度の予想値を返す。"""
    if row.cur_fy_en == fy_en and not pd.isna(getattr(row, f"f_{metric}")):
        return getattr(row, f"f_{metric}")
    if row.nxt_fy_en == fy_en and not pd.isna(getattr(row, f"nx_f_{metric}")):
        return getattr(row, f"nx_f_{metric}")
    return None


def classify(rows: list) -> list[dict]:
    """1銘柄分の開示（開示日時の昇順）を分類し、比較元・比較先の値を返す。"""
    out = []
    for i, r in enumerate(rows):
        event_type = event_type_of(r.doc_type)
        res = {"event_type": event_type, "metric": None, "base_value": None, "new_value": None}
        if event_type == "fy_results":
            for m in PROFIT_METRICS:
                if not pd.isna(getattr(r, m)) and not pd.isna(getattr(r, f"nx_f_{m}")):
                    res.update(metric=m, base_value=getattr(r, m), new_value=getattr(r, f"nx_f_{m}"))
                    break
        elif event_type is not None and r.cur_fy_en is not None:
            metrics = ["div_ann"] if event_type == "div_revision" else PROFIT_METRICS
            for m in metrics:
                new = getattr(r, f"f_{m}")
                if pd.isna(new):
                    continue
                # 同じ事業年度について、直前に開示された予想を探す
                base = next(
                    (v for p in reversed(rows[:i]) if (v := forecast_for_fy(p, r.cur_fy_en, m)) is not None),
                    None,
                )
                if base is not None:
                    res.update(metric="div" if m == "div_ann" else m, base_value=base, new_value=new)
                    break
        out.append(res)
    return out


def change_of(base: float | None, new: float | None) -> tuple[float | None, str | None]:
    if base is None or new is None:
        return None, None
    pct = (new - base) / abs(base) * 100 if base != 0 else None
    if pct is not None:
        pct = max(min(pct, MAX_CHANGE_PCT), -MAX_CHANGE_PCT)  # 比較元がほぼ0のとき列の桁あふれを防ぐ
    diff = pct if pct is not None else (new - base)
    if pct is not None and abs(pct) <= FLAT_PCT or diff == 0:
        return pct, "flat"
    return pct, "up" if diff > 0 else "down"


def reaction_date_of(disc_date: date, disc_time: str, trading_days: list[date]) -> int | None:
    """反応日の trading_days 上の位置を返す。"""
    pos = bisect.bisect_left(trading_days, disc_date)
    if pos < len(trading_days) and trading_days[pos] == disc_date and disc_time >= MARKET_CLOSE:
        pos += 1
    return pos if pos < len(trading_days) else None


def main() -> None:
    start = datetime.now()
    log.info("=== 開示の分類・株価反応計算バッチ 開始 ===")

    with SessionLocal() as db:
        disc = pd.read_sql(text("""
            SELECT disc_no, code, disc_date, disc_time, doc_type, cur_fy_en, nxt_fy_en,
                   op, odp, np, f_op, f_odp, f_np, nx_f_op, nx_f_odp, nx_f_np,
                   div_ann, f_div_ann, nx_f_div_ann
            FROM trader_schema.fin_disclosure
            ORDER BY code, disc_date, disc_time, disc_no
        """), db.connection())
        prices = pd.read_sql(text("""
            SELECT code, trade_date, current_price FROM trader_schema.stock_price
            WHERE current_price IS NOT NULL
        """), db.connection())
        mkt = pd.read_sql(text("""
            SELECT trade_date, mkt_index FROM trader_schema.market_breadth ORDER BY trade_date
        """), db.connection())
        skips = pd.read_sql(text(f"""
            SELECT code, skip_from, skip_until FROM trader_schema.signal_skip
            WHERE reason IN ({", ".join(f"'{r}'" for r in SKIP_REASONS)})
        """), db.connection())

    if disc.empty:
        log.info("開示データなし")
        log.info("=== 開示の分類・株価反応計算バッチ 終了 ===")
        return
    log.info("開示: %d 件", len(disc))

    num_cols = [c for c in disc.columns if c.startswith(("op", "odp", "np", "f_", "nx_f_", "div_"))]
    disc[num_cols] = disc[num_cols].astype(float)
    for c in ["disc_date", "cur_fy_en", "nxt_fy_en"]:
        disc[c] = pd.to_datetime(disc[c]).dt.date

    classified = []
    for _, grp in disc.groupby("code", sort=False):
        classified.extend(classify(list(grp.itertuples(index=False))))
    disc = pd.concat([disc.reset_index(drop=True), pd.DataFrame(classified)], axis=1)
    changes = [change_of(b, n) for b, n in zip(disc["base_value"], disc["new_value"])]
    disc["change_pct"] = [c[0] for c in changes]
    disc["direction"] = [c[1] for c in changes]

    # 株価の反応（取引日は market_breadth の日付を使う）
    trading_days = [pd.Timestamp(d).date() for d in mkt["trade_date"]]
    mkt_index = mkt["mkt_index"].astype(float).to_numpy()
    price = prices.assign(current_price=prices["current_price"].astype(float)).pivot(
        index="trade_date", columns="code", values="current_price"
    )
    price.index = [pd.Timestamp(d).date() for d in price.index]
    price = price.reindex(trading_days)

    def ret(code: str, i: int, j: int) -> float | None:
        if i < 0 or j >= len(trading_days) or code not in price.columns:
            return None
        p0, p1 = price.at[trading_days[i], code], price.at[trading_days[j], code]
        if np.isnan(p0) or np.isnan(p1):
            return None
        return ((p1 / p0 - 1) - (mkt_index[j] / mkt_index[i] - 1)) * 100

    def skipped(code: str, d: date) -> bool:
        s = skips[skips["code"] == code]
        return bool(((s["skip_from"] <= d) & (s["skip_until"] >= d)).any())

    results = []
    for r in disc.itertuples(index=False):
        pos = reaction_date_of(r.disc_date, r.disc_time, trading_days) if r.event_type else None
        rec = {"reaction_date": None, "reaction_excess": None, "drift_5d": None, "drift_20d": None}
        if pos is not None and pos > 0 and not skipped(r.code, trading_days[pos]):
            rec["reaction_date"] = trading_days[pos]
            rec["reaction_excess"] = ret(r.code, pos - 1, pos)
            for n in DRIFT_DAYS:
                rec[f"drift_{n}d"] = ret(r.code, pos, pos + n)
        results.append(rec)
    disc = pd.concat([disc, pd.DataFrame(results)], axis=1)

    def clean(v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return None
        return round(v, 4) if isinstance(v, float) else v

    params = [{"disc_no": r["disc_no"], **{c: clean(r[c]) for c in RESULT_COLS}} for r in disc.to_dict("records")]
    set_clause = ", ".join(f"{c} = :{c}" for c in RESULT_COLS)
    with SessionLocal() as db:
        db.execute(text(f"UPDATE trader_schema.fin_disclosure SET {set_clause} WHERE disc_no = :disc_no"), params)
        db.commit()

    counts = disc.dropna(subset=["direction"]).groupby(["event_type", "direction"]).size()
    log.info("分類結果:\n%s", counts.to_string())
    log.info("株価反応を計算できた開示: %d 件", int(disc["reaction_excess"].notna().sum()))
    elapsed = (datetime.now() - start).total_seconds()
    log.info("完了 (%.1f 秒)", elapsed)
    log.info("=== 開示の分類・株価反応計算バッチ 終了 ===")


if __name__ == "__main__":
    main()
