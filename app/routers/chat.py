"""
株価チャットボット用エンドポイント。

毒舌キャラクターAI（役割1）が、株取引の相談として妥当かどうかを判定し、
そのままキャラクターとしての返答文を返す。株取引の相談内容そのものに対する
実際の分析回答（役割2）はまだ未実装。Tool Use で使う予定のツール定義も
あわせて用意する。
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.llm_client import classify_and_reply

router = APIRouter(prefix="/chat", tags=["chat"])


# ---------------------------------------------------------------------------
# ツール定義（Claude Tool Use 用スキーマ）
# LLM 連携実装時に、ここで定義した name に対応する実行ロジック
# （Cloud SQL への問い合わせ）を追加する。
# ---------------------------------------------------------------------------

CHAT_TOOLS: list[dict] = [
    {
        "name": "get_signal_stats",
        "description": (
            "シグナル種別・業種・集計期間ごとの勝率・平均リターンなどの統計を取得する。"
            "「勝率は？」「買い時か」といった質問で使う。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "signal_type": {
                    "type": "string",
                    "description": (
                        "シグナル種別（golden_cross / dead_cross / rsi_oversold / "
                        "rsi_overbought / bb_lower_touch / bb_upper_touch / volume_surge_up）"
                    ),
                },
                "industry": {
                    "type": "string",
                    "description": "業種名。指定しない場合は全業種合計。",
                },
                "period": {
                    "type": "integer",
                    "description": "集計期間（日数）",
                    "enum": [3, 5, 10, 20],
                },
            },
            "required": ["signal_type"],
        },
    },
    {
        "name": "get_recent_signals",
        "description": "指定した銘柄コードの直近の売買シグナル履歴を取得する。",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "証券コード（例: \"7203\"）"},
                "limit": {"type": "integer", "description": "取得件数（デフォルト10）"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "get_price_history",
        "description": "指定した銘柄コードの直近の株価履歴（終値・出来高など）を取得する。",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "証券コード（例: \"7203\"）"},
                "days": {"type": "integer", "description": "取得日数（デフォルト60）"},
            },
            "required": ["code"],
        },
    },
]


class ChatMessage(BaseModel):
    role: str  # "user" または "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


class ChatResponse(BaseModel):
    reply: str


@router.post("", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """チャットメッセージを受け取り、毒舌キャラクターAIの判定結果をそのまま返す。"""
    result = classify_and_reply(req.message)
    return ChatResponse(reply=result.reply)
