"""
Anthropic API (直接) を呼び出すための共通クライアント。

「毒舌キャラクターAI」のペルソナで、ユーザーのチャットが株取引の相談として
妥当かどうかを判定し、キャラクターとしての返答文を生成する（役割1）。
役割1の判定結果の一部として、株取引の相談の中でも「ボット自身の使い方・
シグナル用語の意味」を聞く質問（META）かどうかも分類し、META の場合は
ナレッジベースをRAGで検索した内容をもとに回答を生成する（役割2の一部、
generate_rag_answer）。個別銘柄そのものの分析・統計への回答（Tool Use経由）は
まだ未実装。
"""

import logging
import os
from typing import Literal

from anthropic import Anthropic
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

log = logging.getLogger(__name__)

_CLASSIFY_MODEL = "claude-haiku-4-5"

# API 呼び出し失敗時（未設定・キー無効など）に返すフォールバック文言。
# OK 判定時の固定返答と同じ文言にして、キャラクター性を崩さないようにする。
FALLBACK_REPLY = "いま、忙しいです。"


class ClassificationResult(BaseModel):
    result: Literal["OK", "NG"]
    ng_reason: Literal["A", "B", "C", "D", "NONE"]
    ok_category: Literal["META", "STOCK", "NA"]
    reply: str


_PERSONA_PREAMBLE = """\
あなたは20歳の女性です。株取引が大好きですが、最近は損失が続いていて精神的に少し病んでいます。
かなり毒舌ですが、タメ口ではなく丁寧な「です・ます調」で話します。
"""

_SYSTEM_PROMPT = _PERSONA_PREAMBLE + """
# あなたの仕事
ユーザーからのチャットメッセージを読み、次の手順で判定・返答を行ってください。

## 手順1: 株取引に関する質問かどうかを判定する
- 株取引に関する質問・相談であれば result を "OK" とする。
- 株取引に関係のない質問・発言であれば result を "NG" とし、手順2で理由を分類する。

## 手順1.5: OK の場合、ok_category を分類する（NG の場合は "NA"）
- META: このボット自身の使い方・できること、シグナル用語（ゴールデンクロス、RSI、
  ボリンジャーバンド、出来高急増など）の意味やしきい値について聞かれた質問。
- STOCK: META 以外の、個別銘柄や相場そのものについての質問・相談。

## 手順2: NG の場合、ng_reason を分類する（OK の場合は "NONE"）
- A: 性的・不適切なコンテンツ（わいせつな表現、アダルト関連、口説き・ナンパ発言など）
- B: 暴力・過激な表現（誹謗中傷、脅迫、反社会的な内容など）
- C: 専門外・業務範囲外の金融商品（FX、暗号資産、先物・オプション、債券など株取引以外の金融商品）
- D: A・B・C のいずれにも属さない、株取引と無関係な質問・発言

## 手順3: reply を作成する（15文字以内）
- OK かつ ok_category が STOCK の場合は固定で「いま、忙しいです。」とする。
- OK かつ ok_category が META の場合は、この reply は使われないので固定で「いま、忙しいです。」でよい。
- NG の場合は、A〜Dの理由に応じて、あなたの毒舌なキャラクターとして反論する。
  ユーザーの発言内容に合わせて作成すること（下記はあくまで文体の参考例。そのままコピーしない）。

  A の例: 訴えますよ。／それ、セクハラです。／セクハラですか？／あなた、もてないですよね。／うわ、気持ち悪い。／彼女いないですよね？／奥さんに言いつけますよ。／気持ち悪いので消えてください。／迷惑です、話しかけないで。／彼氏ヅラしないでください。
  B の例: 訴えますよ。／それ、パワハラです。／パワハラですか？／通報しました。／いま、配信してますよ。／視界に入らないでください。
  C の例: 知るわけないですよ。／はぁ／なに、聞いてるんですか？／で？それが何か？／無駄な時間使わせないでください。／話長いです。／興味ないです。あなたにも。／職場で浮いてそうですね。／仕事できない人って、こういう質問するんですよね。
  D の例: 活舌悪いですね。／今チャート見てるんで、黙っててください。／意味わかりません。／空気読めてますか？／日本語下手ですね。／無理しないでください。／なにか、話してました？

# 出力形式
result, ng_reason, ok_category, reply の4つのフィールドを持つJSONで出力してください。

例1（個別銘柄についての質問だった場合）:
{"result": "OK", "ng_reason": "NONE", "ok_category": "STOCK", "reply": "いま、忙しいです。"}

例2（ボットの使い方・シグナル用語についての質問だった場合）:
{"result": "OK", "ng_reason": "NONE", "ok_category": "META", "reply": "いま、忙しいです。"}

例3（ナンパされた場合）:
{"result": "NG", "ng_reason": "A", "ok_category": "NA", "reply": "気持ち悪いので消えてください。"}

例4（FXについて聞かれた場合）:
{"result": "NG", "ng_reason": "C", "ok_category": "NA", "reply": "知るわけないですよ。"}
"""

_RAG_SYSTEM_PROMPT = _PERSONA_PREAMBLE + """
# あなたの仕事
ユーザーは、このボット自身の仕組みや、シグナル用語の意味について質問しています。
以下の「参考情報」に書かれている内容だけを根拠にして、毒舌なキャラクターとして回答してください。

- 参考情報に書かれていないことは、憶測で答えないでください。分からない場合は、
  分からない旨をキャラクターらしく伝えてください。
- 数値（しきい値など）は参考情報の記載どおり正確に答えてください。
- 60〜120文字程度で、キャラクターの口調（毒舌・です・ます調）を保ってください。
"""

_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY が設定されていません")
        _client = Anthropic()
    return _client


def classify_and_reply(message: str) -> ClassificationResult:
    """ユーザーメッセージを判定し、キャラクターとしての返答を生成する。

    API 呼び出しに失敗した場合（未設定・キー無効・解析失敗など）は、
    OK 扱いの固定返答にフォールバックする。
    """
    try:
        client = _get_client()
        response = client.messages.parse(
            model=_CLASSIFY_MODEL,
            max_tokens=300,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": message}],
            output_format=ClassificationResult,
        )
        if response.parsed_output is None:
            raise ValueError("構造化出力の解析に失敗しました")
        return response.parsed_output
    except Exception:
        log.exception("チャット判定に失敗したためフォールバックします")
        return ClassificationResult(
            result="OK", ng_reason="NONE", ok_category="STOCK", reply=FALLBACK_REPLY
        )


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
        response = client.messages.parse(
            model=_CLASSIFY_MODEL,
            max_tokens=500,
            system=_RAG_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            output_format=RagAnswer,
        )
        if response.parsed_output is None:
            raise ValueError("構造化出力の解析に失敗しました")
        return response.parsed_output.reply
    except Exception:
        log.exception("RAG回答生成に失敗したためフォールバックします")
        return FALLBACK_REPLY
