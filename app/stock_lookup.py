"""
チャットメッセージから、実在する銘柄コード・銘柄名の候補を機械的に抽出するユーティリティ。

ここでの抽出はあくまで機械的な候補出しであり、抽出された数字・文字列が実際に
銘柄コード・銘柄名として使われているかどうか（株価や出来高などの別の数字の
可能性はないか）の最終判断は、呼び出し元の LLM に委ねる。
"""

import re
import unicodedata

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.stock_master import StockMaster


class StockRef(BaseModel):
    """銘柄コード・銘柄名の組。API のリクエスト/レスポンス、および内部での
    銘柄参照（現在選択中の銘柄など）に共通して使う。"""

    code: str
    name: str


# JPX の証券コードは4桁の数字が基本（前後に別の数字が連続しないもののみを候補とする）。
_CODE_RE = re.compile(r"(?<!\d)\d{4}(?!\d)")

# 銘柄名の先頭何文字が一致すればグループ会社などの部分一致とみなすか。
_NAME_PREFIX_LEN = 4

# メッセージ側の断片が短すぎて無関係な銘柄まで拾いすぎないようにする下限文字数。
_MIN_MESSAGE_FRAGMENT_LEN = 2

# 銘柄コードの完全一致は最も確実な一致なので、他のどの一致パターンよりも
# 常に優先されるよう、十分大きいスコアを固定で割り当てる。
_CODE_MATCH_SCORE = 1000


def _common_prefix_len(a: str, b: str) -> int:
    """2つの文字列の先頭から一致している文字数を返す。"""
    n = 0
    for ca, cb in zip(a, b):
        if ca != cb:
            break
        n += 1
    return n


def _match_score(stock: StockMaster, message: str, message_stripped: str, codes_in_message: set[str]) -> int:
    """銘柄とメッセージの一致の強さをスコアとして返す（一致なしは0）。

    銘柄コードの完全一致・銘柄名そのものの完全一致・部分一致のすべてを同じ
    スケールで比較できるようにする。一致の長さが長いほど強い一致とみなす:
    - 銘柄コードの完全一致: 常に最優先（_CODE_MATCH_SCORE）
    - 銘柄名そのものがメッセージに含まれる: 銘柄名の文字数
    - 銘柄名の先頭 _NAME_PREFIX_LEN 文字がメッセージに含まれる: _NAME_PREFIX_LEN
    - メッセージの先頭部分と銘柄名の先頭部分が一致している: その一致文字数
    """
    if stock.code in codes_in_message:
        return _CODE_MATCH_SCORE
    if stock.name in message:
        return len(stock.name)

    forward_score = (
        _NAME_PREFIX_LEN
        if len(stock.name) >= _NAME_PREFIX_LEN and stock.name[:_NAME_PREFIX_LEN] in message
        else 0
    )
    reverse_score = _common_prefix_len(message_stripped, stock.name)
    return max(forward_score, reverse_score)


def find_candidate_stocks(db: Session, message: str) -> list[StockMaster]:
    """メッセージ中の数字・文字列から、実在する銘柄の候補を抽出する。

    全銘柄について _match_score でメッセージとの一致の強さをスコアリングし、
    最もスコアが高い銘柄群だけを候補として返す。全パターンを同じスケールで
    比較することで、「トヨタ自動車はどう？」のように完全な銘柄名（6文字一致）
    が含まれるメッセージで、たまたま3文字だけ一致する無関係な銘柄（例:
    「トヨタ紡織」）が紛れ込むことを防ぐ。

    銘柄コードは全角数字（例:「９９８４」）で入力される可能性があるため、
    NFKC正規化で半角に統一してから照合する（stock_master.code は半角で
    格納されているため）。
    """
    message = unicodedata.normalize("NFKC", message)
    codes_in_message = set(_CODE_RE.findall(message))
    message_stripped = message.strip()
    stocks = db.query(StockMaster).all()

    scored = [
        (stock, score)
        for stock in stocks
        for score in [_match_score(stock, message, message_stripped, codes_in_message)]
        if score >= _MIN_MESSAGE_FRAGMENT_LEN
    ]
    if not scored:
        return []

    max_score = max(score for _, score in scored)
    return [stock for stock, score in scored if score == max_score]
