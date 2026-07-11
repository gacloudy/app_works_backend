"""
チャットメッセージから、実在する銘柄コード・銘柄名の候補を機械的に抽出するユーティリティ。

ここでの抽出はあくまで機械的な候補出しであり、抽出された数字・文字列が実際に
銘柄コード・銘柄名として使われているかどうか（株価や出来高などの別の数字の
可能性はないか）の最終判断は、呼び出し元の LLM に委ねる。
"""

import re

from sqlalchemy.orm import Session

from app.models.stock_master import StockMaster

# JPX の証券コードは4桁の数字が基本（前後に別の数字が連続しないもののみを候補とする）。
_CODE_RE = re.compile(r"(?<!\d)\d{4}(?!\d)")

# 銘柄名の先頭何文字が一致すればグループ会社などの部分一致とみなすか。
_NAME_PREFIX_LEN = 4


def find_candidate_stocks(db: Session, message: str) -> list[StockMaster]:
    """メッセージ中の数字・文字列から、実在する銘柄の候補を抽出する。

    - メッセージ中の4桁の数字が銘柄コードと完全一致するもの
    - 銘柄名そのもの、または銘柄名の先頭 _NAME_PREFIX_LEN 文字がメッセージに
      含まれるもの（例: 「三井住友」が「三井住友トラストグループ」「三井住友
      フィナンシャルグループ」の両方にヒットするような部分一致も候補に含める）
    をそれぞれ候補として拾う。
    """
    codes_in_message = set(_CODE_RE.findall(message))
    stocks = db.query(StockMaster).all()

    candidates = []
    for stock in stocks:
        if stock.code in codes_in_message:
            candidates.append(stock)
        elif stock.name in message:
            candidates.append(stock)
        elif len(stock.name) >= _NAME_PREFIX_LEN and stock.name[:_NAME_PREFIX_LEN] in message:
            candidates.append(stock)
    return candidates
