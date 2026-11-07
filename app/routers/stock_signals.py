"""
銘柄ごとに「どのシグナルを頼りに売買したら、どれだけ利益・損失が出たか」を計算して返す API。

売買はすべて「シグナルが出た翌取引日の始値」で行う（シグナルは終値で確定するため）。株価は分割調整済み。

(A) 保有日数固定: シグナルの翌日始値で買い、シグナル日から N 取引日後の終値で売る（N = 5 / 10 / 20）
    - 買いシグナル: 損益 = 売値 / 買値 − 1 − 手数料（往復 COST_PCT %）
    - 売りシグナル: 「持っていた株をその日に売っていたら避けられた値下がり」= −(N 日後の終値 / 翌日始値 − 1)。
                    プラスなら売って正解、マイナスなら売らずに持っていた方が良かった（値上がりを逃した）
    - 累計は、保有中に出た同じシグナルは無視して1回ずつ売買した場合の複利（買いシグナルのみ）
(B) 買いシグナル → 売りシグナル: 買いシグナルの翌日始値で買い、反対の売りシグナルの翌日始値で売る。
    データの最終日まで売りシグナルが出なければ、最終日の終値で評価する（holding = true）
比較: 期間の最初の始値で買い、最終日の終値まで持ち続けた場合（buy_hold_return）
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db

router = APIRouter(prefix="/stocks", tags=["stock-signals"])

COST_PCT = 0.1
PERIODS = [5, 10, 20]
FEW_TRADES = 5  # これ未満の回数は偶然の影響が大きいとみなす
SIGNAL_SIDE = {
    "golden_cross": "buy", "rsi_oversold": "buy", "bb_lower_touch": "buy", "volume_surge_up": "buy",
    "dead_cross": "sell", "rsi_overbought": "sell", "bb_upper_touch": "sell",
}
PAIRS = [
    ("golden_cross", "dead_cross"),
    ("rsi_oversold", "rsi_overbought"),
    ("bb_lower_touch", "bb_upper_touch"),
]


class SignalResult(BaseModel):
    signal_type: str
    side: str                      # buy / sell
    count: int                     # 発生回数
    completed: int                 # N 日後まで結果が出ている回数
    win_rate: float | None         # 買い: 利益が出た割合 / 売り: 売って正解だった割合（%）
    avg_return: float | None       # 1回あたりの平均（%）。売りは避けられた値下がり
    best: float | None
    worst: float | None
    cumulative_return: float | None  # 1回ずつ売買した場合の累計（複利、%）。買いのみ
    cumulative_trades: int | None
    vs_industry: float | None      # 同じ日に同じ業種の全銘柄で同じ売買をした平均との差（%）。売りは符号を反転
    all_stocks_avg: float | None   # 全銘柄で同じシグナルを使った場合の平均（%）
    few_trades: bool               # 回数が少なく偶然の影響が大きい


class PeriodResult(BaseModel):
    period: int
    signals: list[SignalResult]


class PairTrade(BaseModel):
    entry_date: date
    entry_price: float
    exit_date: date
    exit_price: float
    return_pct: float              # 手数料差し引き後（%）
    holding_days: int              # 保有した取引日数
    holding: bool                  # まだ売りシグナルが出ておらず、最終日の終値で評価している


class PairResult(BaseModel):
    buy_signal: str
    sell_signal: str
    trade_count: int
    win_rate: float | None
    avg_return: float | None
    total_return: float | None     # 複利の累計（%）
    avg_holding_days: float | None
    exposure_pct: float | None     # 期間中に株を持っていた日の割合（%）
    trades: list[PairTrade]


class SignalEvent(BaseModel):
    signal_date: date
    signal_type: str
    side: str
    price: float | None            # シグナル日の終値
    entry_date: date | None
    entry_price: float | None      # 翌日始値
    results: dict[str, float | None]  # "5" / "10" / "20" → 損益（買い）または避けられた値下がり（売り）、%


class SignalPerformance(BaseModel):
    code: str
    start_date: date | None
    end_date: date | None
    trading_days: int
    buy_hold_return: float | None
    by_period: list[PeriodResult]
    pairs: list[PairResult]
    events: list[SignalEvent]


def _round(v: float | None, digits: int = 2) -> float | None:
    return None if v is None else round(v, digits)


def _pct(a: float, b: float) -> float:
    return (b / a - 1) * 100


@router.get("/{code}/signal-performance", response_model=SignalPerformance)
def signal_performance(code: str, db: Session = Depends(get_db)):
    """指定銘柄について、シグナルを頼りに売買した場合の損益を返す。"""
    prices = db.execute(text("""
        SELECT trade_date, open_price, current_price FROM trader_schema.stock_price
        WHERE code = :code AND current_price IS NOT NULL ORDER BY trade_date
    """), {"code": code}).fetchall()
    if not prices:
        raise HTTPException(status_code=404, detail="株価データがありません")
    dates = [r[0] for r in prices]
    opens = [float(r[1]) if r[1] is not None else None for r in prices]
    closes = [float(r[2]) for r in prices]
    pos = {d: i for i, d in enumerate(dates)}
    last = len(dates) - 1

    signals = db.execute(text("""
        SELECT signal_date, signal_type FROM trader_schema.signal_history
        WHERE code = :code ORDER BY signal_date, signal_type
    """), {"code": code}).fetchall()
    signals = [(d, t) for d, t in signals if d in pos and t in SIGNAL_SIDE]

    lifts = {
        (r[0], r[1]): r[2:]
        for r in db.execute(text("""
            SELECT signal_date, signal_type, lift_ind_5d, lift_ind_10d, lift_ind_20d
            FROM trader_schema.signal_trades WHERE code = :code
        """), {"code": code}).fetchall()
    }
    all_avgs = {
        (r[0], r[1]): float(r[2]) if r[2] is not None else None
        for r in db.execute(text("""
            SELECT signal_type, period, avg_net_return FROM trader_schema.signal_segment_stats
            WHERE segment_type = 'all'
        """)).fetchall()
    }

    def trade_value(i: int, n: int, side: str) -> float | None:
        """シグナル日 i から N 日保有した場合の値（買いは手数料差し引き後の損益、売りは避けられた値下がり）。"""
        if i + n > last or opens[i + 1] is None or opens[i + 1] <= 0:
            return None
        raw = _pct(opens[i + 1], closes[i + n])
        return raw - COST_PCT if side == "buy" else -raw

    # (A) 保有日数固定
    by_period = []
    for n in PERIODS:
        results = []
        for stype, side in SIGNAL_SIDE.items():
            idxs = [pos[d] for d, t in signals if t == stype]
            values = [v for v in (trade_value(i, n, side) for i in idxs) if v is not None]

            cumulative, cum_trades = None, None
            if side == "buy" and values:
                growth, cum_trades, busy_until = 1.0, 0, -1
                for i in idxs:
                    v = trade_value(i, n, side)
                    if v is None or i <= busy_until:
                        continue  # まだ前の株を持っている
                    growth *= 1 + v / 100
                    cum_trades += 1
                    busy_until = i + n
                cumulative = (growth - 1) * 100

            lift_vals = []
            for d, t in signals:
                if t != stype or (d, t) not in lifts:
                    continue
                v = lifts[(d, t)][PERIODS.index(n)]
                if v is not None:
                    lift_vals.append(float(v) if side == "buy" else -float(v))
            all_avg = all_avgs.get((stype, n))
            if all_avg is not None and side == "sell":
                all_avg = -(all_avg + COST_PCT)

            results.append(SignalResult(
                signal_type=stype,
                side=side,
                count=len(idxs),
                completed=len(values),
                win_rate=_round(sum(v > 0 for v in values) / len(values) * 100, 1) if values else None,
                avg_return=_round(sum(values) / len(values)) if values else None,
                best=_round(max(values)) if values else None,
                worst=_round(min(values)) if values else None,
                cumulative_return=_round(cumulative),
                cumulative_trades=cum_trades,
                vs_industry=_round(sum(lift_vals) / len(lift_vals)) if lift_vals else None,
                all_stocks_avg=_round(all_avg),
                few_trades=len(values) < FEW_TRADES,
            ))
        by_period.append(PeriodResult(period=n, signals=results))

    # (B) 買いシグナル → 売りシグナル
    pairs = []
    for buy_sig, sell_sig in PAIRS:
        buy_days = {pos[d] for d, t in signals if t == buy_sig}
        sell_days = {pos[d] for d, t in signals if t == sell_sig}
        trades, entry = [], None
        for i in range(last + 1):
            if entry is None:
                if i in buy_days and i + 1 <= last and opens[i + 1]:
                    entry = i + 1
            elif i >= entry and i in sell_days and i + 1 <= last and opens[i + 1]:
                trades.append((entry, i + 1, opens[i + 1], False))
                entry = None
        if entry is not None:
            trades.append((entry, last, closes[last], True))

        pair_trades = [
            PairTrade(
                entry_date=dates[e], entry_price=opens[e], exit_date=dates[x], exit_price=px,
                return_pct=round(_pct(opens[e], px) - COST_PCT, 2), holding_days=x - e, holding=h,
            )
            for e, x, px, h in trades
        ]
        rets = [t.return_pct for t in pair_trades]
        growth = 1.0
        for r in rets:
            growth *= 1 + r / 100
        held = sum(t.holding_days for t in pair_trades)
        pairs.append(PairResult(
            buy_signal=buy_sig,
            sell_signal=sell_sig,
            trade_count=len(pair_trades),
            win_rate=_round(sum(r > 0 for r in rets) / len(rets) * 100, 1) if rets else None,
            avg_return=_round(sum(rets) / len(rets)) if rets else None,
            total_return=_round((growth - 1) * 100) if rets else None,
            avg_holding_days=_round(held / len(pair_trades), 1) if pair_trades else None,
            exposure_pct=_round(held / max(last, 1) * 100, 1),
            trades=pair_trades,
        ))

    first_open = next((i for i, o in enumerate(opens) if o), None)
    buy_hold = _pct(opens[first_open], closes[last]) if first_open is not None else None

    events = []
    for d, t in reversed(signals):
        i = pos[d]
        side = SIGNAL_SIDE[t]
        has_entry = i + 1 <= last and opens[i + 1]
        events.append(SignalEvent(
            signal_date=d,
            signal_type=t,
            side=side,
            price=closes[i],
            entry_date=dates[i + 1] if has_entry else None,
            entry_price=opens[i + 1] if has_entry else None,
            results={str(n): _round(trade_value(i, n, side)) for n in PERIODS},
        ))

    return SignalPerformance(
        code=code,
        start_date=dates[0],
        end_date=dates[last],
        trading_days=len(dates),
        buy_hold_return=_round(buy_hold),
        by_period=by_period,
        pairs=pairs,
        events=events,
    )
