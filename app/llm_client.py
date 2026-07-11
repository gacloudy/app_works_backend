"""
Anthropic API (直接) を呼び出すための共通クライアント。

判定と返答生成の責務を分離している。
- classify_message: ユーザーのチャットを読み、後続でどのモードのAIに処理させる
  べきかカテゴリだけを判定する（返答文は生成しない）。銘柄コード・銘柄名の
  候補（stock_lookup.find_candidate_stocks による機械的な抽出結果）をあわせて
  渡し、実際にその銘柄について聞いているかどうかの文脈判断はLLMに委ねる。
  - Glossary: シグナル用語の意味について聞かれた質問。
  - Selected: 特定の個別銘柄について質問・相談している場合。
  - Other: それ以外すべて（今後、他のカテゴリを追加予定）。
- generate_ng_reply: Other 判定された発言に対し、毒舌なキャラクターとして反応する。
- generate_rag_answer: Glossary 判定された質問に対し、ナレッジベースをRAGで
  検索した内容をもとに回答する。
- generate_selected_reply: Selected 判定された質問に対して回答する。
  実際の分析ロジックは未実装のため、いまは固定文言を返す。
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Literal

from anthropic import Anthropic
from dotenv import load_dotenv
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.stock_master import StockMaster
from app.stock_lookup import find_candidate_stocks

load_dotenv()

log = logging.getLogger(__name__)

_CLASSIFY_MODEL = "claude-haiku-4-5"

# API 呼び出し失敗時（未設定・キー無効など）に返すフォールバック文言。
# OK 判定時の固定返答と同じ文言にして、キャラクター性を崩さないようにする。
FALLBACK_REPLY = "いま、忙しいです。"


class ClassificationResult(BaseModel):
    category: Literal["Glossary", "Selected", "Other"]


@dataclass
class ClassifyOutcome:
    """classify_message の戻り値。LLMの分類結果と、その根拠となった銘柄候補の両方を持つ。"""

    category: Literal["Glossary", "Selected", "Other"]
    candidates: list[StockMaster] = field(default_factory=list)


_PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")


def _read_prompt(filename: str) -> str:
    """プロンプトファイルをその都度読み込む（キャッシュしない）。

    サーバーを再起動せずにプロンプトの変更をすぐ反映できるようにするため、
    モジュール読み込み時の定数ではなく、呼び出しのたびにファイルを読む。
    """
    with open(os.path.join(_PROMPTS_DIR, filename), encoding="utf-8") as f:
        return f.read()


_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY が設定されていません")
        _client = Anthropic()
    return _client


def classify_message(message: str, db: Session) -> ClassifyOutcome:
    """ユーザーメッセージを読み、後続でどのモードのAIに処理させるべきかを判定する。

    stock_master から機械的に抽出した銘柄コード・銘柄名の候補をあわせて渡し、
    実際にその銘柄について聞いているかどうかの文脈判断はLLMに委ねる。
    返答文は生成しない。API 呼び出しに失敗した場合（未設定・キー無効・解析失敗など）は、
    Other 扱いにフォールバックする（呼び出し元の generate_ng_reply がさらに
    固定返答にフォールバックする）。
    """
    candidates = find_candidate_stocks(db, message)
    try:
        if candidates:
            candidate_lines = "\n".join(f"- {s.code}: {s.name}" for s in candidates)
        else:
            candidate_lines = "（候補なし）"
        user_content = f"# 銘柄候補\n{candidate_lines}\n\n# ユーザーのメッセージ\n{message}"

        client = _get_client()
        system_prompt = _read_prompt("00_persona.txt") + "\n" + _read_prompt("01_classify.txt")
        response = client.messages.parse(
            model=_CLASSIFY_MODEL,
            max_tokens=100,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
            output_format=ClassificationResult,
        )
        if response.parsed_output is None:
            raise ValueError("構造化出力の解析に失敗しました")
        return ClassifyOutcome(category=response.parsed_output.category, candidates=candidates)
    except Exception:
        log.exception("チャット判定に失敗したためフォールバックします")
        return ClassifyOutcome(category="Other", candidates=candidates)


class NgReply(BaseModel):
    reply: str


def generate_ng_reply(message: str) -> str:
    """Other判定された発言に対して、内容に応じた毒舌な反応を生成する。

    API 呼び出しに失敗した場合は、固定フォールバック文言を返す。
    """
    try:
        client = _get_client()
        system_prompt = _read_prompt("00_persona.txt") + "\n" + _read_prompt("02_01_other.txt")
        response = client.messages.parse(
            model=_CLASSIFY_MODEL,
            max_tokens=300,
            system=system_prompt,
            messages=[{"role": "user", "content": message}],
            output_format=NgReply,
        )
        if response.parsed_output is None:
            raise ValueError("構造化出力の解析に失敗しました")
        return response.parsed_output.reply
    except Exception:
        log.exception("反応生成に失敗したためフォールバックします")
        return FALLBACK_REPLY


class SelectedReply(BaseModel):
    reply: str


def generate_selected_reply(message: str) -> str:
    """Selected判定された質問に対して回答する。

    実際の分析ロジックはまだ未実装のため、いまは固定文言を返すだけのプロンプトを使う。
    API 呼び出しに失敗した場合は、固定フォールバック文言を返す。
    """
    try:
        client = _get_client()
        system_prompt = _read_prompt("00_persona.txt") + "\n" + _read_prompt("02_03_selected.txt")
        response = client.messages.parse(
            model=_CLASSIFY_MODEL,
            max_tokens=100,
            system=system_prompt,
            messages=[{"role": "user", "content": message}],
            output_format=SelectedReply,
        )
        if response.parsed_output is None:
            raise ValueError("構造化出力の解析に失敗しました")
        return response.parsed_output.reply
    except Exception:
        log.exception("Selected回答生成に失敗したためフォールバックします")
        return FALLBACK_REPLY


class RagAnswer(BaseModel):
    reply: str


def generate_rag_answer(message: str, context_chunks: list[str]) -> str:
    """ナレッジベースから検索したチャンクを根拠に、キャラクターとして回答文を生成する。

    API 呼び出しに失敗した場合は、役割1と同じ固定フォールバック文言を返す。
    """
    context = "\n\n---\n\n".join(context_chunks)
    user_content = f"# 参考情報\n{context}\n\n# ユーザーの質問\n{message}"
    try:
        client = _get_client()
        system_prompt = _read_prompt("00_persona.txt") + "\n" + _read_prompt("02_02_glossary.txt")
        response = client.messages.parse(
            model=_CLASSIFY_MODEL,
            max_tokens=500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
            output_format=RagAnswer,
        )
        if response.parsed_output is None:
            raise ValueError("構造化出力の解析に失敗しました")
        return response.parsed_output.reply
    except Exception:
        log.exception("RAG回答生成に失敗したためフォールバックします")
        return FALLBACK_REPLY
