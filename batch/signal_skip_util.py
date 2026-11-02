"""
signal_skip テーブル（シグナル分析の除外期間）を参照する共通処理。

detect_signals / update_signal_results / aggregate_stats から利用する。
"""

import pandas as pd
from sqlalchemy import text


def load_skip_windows(db) -> pd.DataFrame:
    """除外期間の一覧を code, skip_from, skip_until の DataFrame で返す。"""
    rows = db.execute(text("""
        SELECT code, skip_from, skip_until
        FROM trader_schema.signal_skip
    """)).fetchall()
    return pd.DataFrame(rows, columns=["code", "skip_from", "skip_until"])


def skipped_mask(df: pd.DataFrame, windows: pd.DataFrame, date_col: str) -> pd.Series:
    """df の各行 (code, date_col) が除外期間に含まれるなら True を返す。"""
    if windows.empty or df.empty:
        return pd.Series(False, index=df.index)
    m = df[["code", date_col]].reset_index().merge(windows, on="code")
    hit = m[(m[date_col] >= m["skip_from"]) & (m[date_col] <= m["skip_until"])]["index"]
    return df.index.to_series().isin(set(hit))
