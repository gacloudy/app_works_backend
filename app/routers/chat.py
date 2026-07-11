"""
株価チャットボット用エンドポイント。

毒舌キャラクターAI（役割1）が、ユーザーのチャットを Glossary（シグナル用語の
意味についての質問）・Selected（特定の個別銘柄についての質問）・Other（それ以外
すべて）に分類する。Glossary はナレッジベースをRAGで検索した内容をもとに回答し、
Selected は（実際の分析ロジックは未実装のため）固定文言を返し、Other は内容に
応じた毒舌な反応を返す。Selected で銘柄候補が複数見つかった場合は、回答文の
かわりに候補一覧を返し、フロントエンドで選択肢として表示する。
"""

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

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatMessage(BaseModel):
    role: str  # "user" または "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


class StockCandidateOut(BaseModel):
    code: str
    name: str


class ChatResponse(BaseModel):
    reply: str
    candidates: list[StockCandidateOut] | None = None


@router.post("", response_model=ChatResponse)
def chat(req: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    """チャットメッセージを受け取り、カテゴリ判定結果に応じて回答を生成する。

    - Glossary: ナレッジベースをRAGで検索した内容をもとに回答を生成する。
    - Selected: 特定の個別銘柄についての質問。
      - 銘柄候補が複数見つかった場合は、回答文のかわりに候補一覧を返す
        （フロントエンドで選択肢として表示し、ユーザーが選ぶと1件に絞り込まれて
        再度リクエストが来る想定）。
      - 候補が1件以下の場合は、そのまま回答する（実際の分析はまだ未実装のため固定文言）。
    - Other: 内容に応じた毒舌な反応を生成する。
    """
    result = classify_message(req.message, db)

    if result.category == "Glossary":
        chunks = search_kb(db, req.message, top_k=3)
        reply = generate_rag_answer(req.message, [c.content for c in chunks])
        return ChatResponse(reply=reply)

    if result.category == "Selected":
        if len(result.candidates) > 1:
            candidates = [StockCandidateOut(code=c.code, name=c.name) for c in result.candidates]
            return ChatResponse(
                reply="どれのこと言ってます？",
                candidates=candidates,
            )
        reply = generate_selected_reply(req.message)
        return ChatResponse(reply=reply)

    reply = generate_ng_reply(req.message)
    return ChatResponse(reply=reply)
