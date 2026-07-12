"""
選択中の銘柄についての基礎情報（業界・株価の値動き）を、チャット回答生成用の
プロンプトに埋め込めるテキストとして組み立てるユーティリティ。
"""

from sqlalchemy.orm import Session

from app.models.stock_master import StockMaster
from app.models.stock_price import StockPrice

# 値動きの推移として遡って提示する営業日数
_PRICE_HISTORY_DAYS = 5


def build_stock_context(db: Session, code: str) -> str | None:
    """指定銘柄の業界・直近の値動きをプロンプト用のテキストにまとめる。

    銘柄マスタに存在しない場合は None を返す。
    """
    stock = db.query(StockMaster).filter(StockMaster.code == code).first()
    if stock is None:
        return None

    lines = [f"銘柄名: {stock.name}", f"業界: {stock.industry}"]

    prices = (
        db.query(StockPrice)
        .filter(StockPrice.code == code)
        .order_by(StockPrice.trade_date.desc())
        .limit(_PRICE_HISTORY_DAYS)
        .all()
    )
    prices.reverse()  # 古い順に並び替え

    if prices:
        latest = prices[-1]
        lines.append(
            f"直近営業日（{latest.trade_date}）: 現在値 {latest.current_price}円"
            f"（前日終値 {latest.prev_close}円、高値 {latest.high_price}円、安値 {latest.low_price}円）"
        )
        if latest.prev_close and latest.current_price:
            change_pct = (latest.current_price - latest.prev_close) / latest.prev_close * 100
            lines.append(f"前日比: {change_pct:+.2f}%")

        history = [f"{p.trade_date}: {p.current_price}円" for p in prices if p.current_price is not None]
        if history:
            lines.append(f"直近{len(history)}営業日の値動き: " + " → ".join(history))
    else:
        lines.append("株価データ: なし")

    return "\n".join(lines)
