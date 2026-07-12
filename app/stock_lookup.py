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

# メッセージ側の断片が短すぎて無関係な銘柄まで拾いすぎないようにする下限文字数。
_MIN_MESSAGE_FRAGMENT_LEN = 2

# 銘柄コードの完全一致は最も確実な一致なので、他のどの一致パターンよりも
# 常に優先されるよう、十分大きいスコアを固定で割り当てる。
_CODE_MATCH_SCORE = 1000


def _longest_common_substring_len(a: str, b: str) -> int:
    """2つの文字列に共通して含まれる、最長の連続一致部分文字列の長さを返す。

    先頭一致（プレフィックス一致）だけでなく、「ＵＦＪ」が「三菱ＵＦＪ
    フィナンシャル・グループ」の途中に含まれるような、文字列中のどの位置に
    ある一致も拾えるようにするための汎用的な一致度計算。
    """
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for ca in a:
        curr = [0] * (len(b) + 1)
        for j, cb in enumerate(b, start=1):
            if ca == cb:
                curr[j] = prev[j - 1] + 1
                best = max(best, curr[j])
        prev = curr
    return best


def _match_score(stock: StockMaster, message: str, message_stripped: str, codes_in_message: set[str]) -> int:
    """銘柄とメッセージの一致の強さをスコアとして返す（一致なしは0）。

    銘柄コードの完全一致・銘柄名そのものの完全一致・部分一致のすべてを同じ
    スケールで比較できるようにする。一致の長さが長いほど強い一致とみなす:
    - 銘柄コードの完全一致: 常に最優先（_CODE_MATCH_SCORE）
    - 銘柄名そのものがメッセージに含まれる: 銘柄名の文字数
    - それ以外: メッセージと銘柄名の最長共通部分文字列の文字数（出現位置は問わない）

    銘柄名はJPXのデータ上、英字部分が全角（例:「ＵＦＪ」）で格納されている
    ことがあるため、比較のたびにNFKC正規化して半角に統一する（呼び出し元の
    message は find_candidate_stocks で既に正規化済み）。
    """
    name = unicodedata.normalize("NFKC", stock.name)

    if stock.code in codes_in_message:
        return _CODE_MATCH_SCORE
    if name in message:
        return len(name)

    return _longest_common_substring_len(message_stripped, name)


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
