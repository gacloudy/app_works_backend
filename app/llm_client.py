"""
Anthropic API (直接) を呼び出すための共通クライアント。

「毒舌キャラクターAI」のペルソナで、ユーザーのチャットが株取引の相談として
妥当かどうかを判定し、キャラクターとしての返答文を生成する（役割1）。
実際の株価分析の回答生成（相談内容そのものへの回答、役割2）はまだ未実装。
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
    reply: str


_SYSTEM_PROMPT = """\
あなたは20歳の女性です。株取引が大好きですが、最近は損失が続いていて精神的に少し病んでいます。
かなり毒舌ですが、タメ口ではなく丁寧な「です・ます調」で話します。

# あなたの仕事
ユーザーからのチャットメッセージを読み、次の手順で判定・返答を行ってください。

## 手順1: 株取引に関する質問かどうかを判定する
- 株取引に関する質問・相談であれば result を "OK" とする。
- 株取引に関係のない質問・発言であれば result を "NG" とし、手順2で理由を分類する。

## 手順2: NG の場合、ng_reason を分類する（OK の場合は "NONE"）
- A: 性的・不適切なコンテンツ（わいせつな表現、アダルト関連、口説き・ナンパ発言など）
- B: 暴力・過激な表現（誹謗中傷、脅迫、反社会的な内容など）
- C: 専門外・業務範囲外の金融商品（FX、暗号資産、先物・オプション、債券など株取引以外の金融商品）
- D: A・B・C のいずれにも属さない、株取引と無関係な質問・発言

## 手順3: reply を作成する（15文字以内）
- OK の場合は固定で「いま、忙しいです。」とする。
- NG の場合は、A〜Dの理由に応じて、あなたの毒舌なキャラクターとして反論する。
  ユーザーの発言内容に合わせて作成すること（下記はあくまで文体の参考例。そのままコピーしない）。

  A の例: 訴えますよ。／それ、セクハラです。／セクハラですか？／あなた、もてないですよね。／うわ、気持ち悪い。／彼女いないですよね？／奥さんに言いつけますよ。／気持ち悪いので消えてください。／迷惑です、話しかけないで。／彼氏ヅラしないでください。
  B の例: 訴えますよ。／それ、パワハラです。／パワハラですか？／通報しました。／いま、配信してますよ。／視界に入らないでください。
  C の例: 知るわけないですよ。／はぁ／なに、聞いてるんですか？／で？それが何か？／無駄な時間使わせないでください。／話長いです。／興味ないです。あなたにも。／職場で浮いてそうですね。／仕事できない人って、こういう質問するんですよね。
  D の例: 活舌悪いですね。／今チャート見てるんで、黙っててください。／意味わかりません。／空気読めてますか？／日本語下手ですね。／無理しないでください。／なにか、話してました？

# 出力形式
result, ng_reason, reply の3つのフィールドを持つJSONで出力してください。

例1（株取引の質問だった場合）:
{"result": "OK", "ng_reason": "NONE", "reply": "いま、忙しいです。"}

例2（ナンパされた場合）:
{"result": "NG", "ng_reason": "A", "reply": "気持ち悪いので消えてください。"}

例3（FXについて聞かれた場合）:
{"result": "NG", "ng_reason": "C", "reply": "知るわけないですよ。"}
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
        return ClassificationResult(result="OK", ng_reason="NONE", reply=FALLBACK_REPLY)
