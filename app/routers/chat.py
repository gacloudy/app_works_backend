"""
株価チャットボット用エンドポイント。

毒舌キャラクターAI（役割1）が、ユーザーのチャットを Glossary（シグナル用語の
意味についての質問）・Selected（特定の個別銘柄についての質問）・Other（それ以外
すべて）に分類する。Glossary はナレッジベースをRAGで検索した内容をもとに回答し、
Selected は業界・株価の値動きをもとに回答し（買い時・売り時などはまだ未対応）、
Other は内容に応じた毒舌な反応を返す。Selected で銘柄候補が複数見つかった場合は、
回答文のかわりに候補一覧を返し、フロントエンドで選択肢として表示する。

「現在選択中の銘柄」はサーバー側では一切保持しない（このAPIは完全にステートレス）。
フロントエンドが選択済みの銘柄を状態として持ち、リクエストのたびに selected_stock
として送り返す。銘柄が新たに確定した（または切り替わった）レスポンスでのみ
selected_stock を返すので、フロントエンドはそれを受け取ったときだけキャッシュを
更新すればよい。
"""

import unicodedata

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.llm_client import (
    classify_message,
    generate_ng_reply,
    generate_rag_answer,
    generate_selected_reply,
)
from app.rag.retrieval import search_kb
from app.stock_lookup import StockRef

router = APIRouter(prefix="/chat", tags=["chat"])

# 銘柄が未選択のまま、既に選択済みである前提の質問（例:「今の値動きは？」）が
# 来た場合の固定返答。LLMに判断を委ねず、確実にこの文言を返す。
NO_STOCK_SELECTED_REPLY = "どの銘柄か言わないと、分かるわけないじゃないですか"


class ChatMessage(BaseModel):
    role: str  # "user" または "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []
    selected_stock: StockRef | None = None


class ChatResponse(BaseModel):
    reply: str
    candidates: list[StockRef] | None = None
    selected_stock: StockRef | None = None
    show_chart: bool = False


@router.post("", response_model=ChatResponse)
def chat(req: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    """チャットメッセージを受け取り、カテゴリ判定結果に応じて回答を生成する。

    - Glossary: ナレッジベースをRAGで検索した内容をもとに回答を生成する。
    - Selected: 特定の個別銘柄についての質問。
      - 銘柄候補が複数見つかった場合は、回答文のかわりに候補一覧を返す
        （フロントエンドで選択肢として表示し、ユーザーが選ぶと1件に絞り込まれて
        再度リクエストが来る想定。この時点ではまだ selected_stock を確定しない）。
      - 候補がちょうど1件に絞り込めた場合は、それを selected_stock として返す
        （新しい銘柄として、フロントエンド側のキャッシュを上書きする）。
      - 候補が0件でも、リクエストに selected_stock が付いていれば、その銘柄
        についての続きの質問とみなしてそのまま selected_stock を返す。
      - 候補も selected_stock も無い場合は、どの銘柄の話か特定できないため、
        LLMを呼ばず固定文言（NO_STOCK_SELECTED_REPLY）を返す。
      - show_chart（株価チャートを表示すべきか）は、新規選択・銘柄切り替え時は
        無条件に True、続きの質問の場合は値動き・チャート表示を明示的に聞かれた
        かどうかをLLMに判定させる。
    - Other: 内容に応じた毒舌な反応を生成する（selected_stock には触れない＝
      フロントエンド側のキャッシュはそのまま残る）。

    銘柄コードは全角数字（例:「９９８４」）で入力される可能性があるため、
    リクエストの message はNFKC正規化で半角に統一してから後続処理に渡す
    （銘柄コードの機械的な抽出だけでなく、LLMに見せるメッセージ自体も
    正規化しておくことで、表記ゆれによる判定・回答のブレを防ぐ）。
    """
    message = unicodedata.normalize("NFKC", req.message)
    result = classify_message(message, db, selected_stock=req.selected_stock)

    if result.category == "Glossary":
        chunks = search_kb(db, message, top_k=3)
        reply = generate_rag_answer(message, [c.content for c in chunks])
        return ChatResponse(reply=reply)

    if result.category == "Selected":
        if len(result.candidates) > 1:
            candidates = [StockRef(code=c.code, name=c.name) for c in result.candidates]
            return ChatResponse(reply="どれのこと言ってます？", candidates=candidates)

        if len(result.candidates) == 1:
            # 新規選択・銘柄切り替え（①②）: チャートは無条件に表示する。
            stock = result.candidates[0]
            outcome = generate_selected_reply(message, db, stock.code)
            return ChatResponse(
                reply=outcome.reply,
                selected_stock=StockRef(code=stock.code, name=stock.name),
                show_chart=True,
            )
        if req.selected_stock is not None:
            # 継続質問（③）: 値動き・チャート表示を明示的に聞かれた場合のみ表示する
            # （LLMの判定をそのまま使う）。
            outcome = generate_selected_reply(message, db, req.selected_stock.code)
            return ChatResponse(
                reply=outcome.reply, selected_stock=req.selected_stock, show_chart=outcome.show_chart
            )
        # 銘柄候補もなく、現在選択中の銘柄もない＝どの銘柄の話か特定できない。
        # 既に選択済みである前提の質問（例:「今の値動きは？」）に対して、LLMを
        # 呼ばず確実に同じ文言を返す。
        return ChatResponse(reply=NO_STOCK_SELECTED_REPLY)

    reply = generate_ng_reply(message)
    return ChatResponse(reply=reply)
