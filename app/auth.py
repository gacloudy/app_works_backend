import os

from fastapi import HTTPException, Request
from google.auth import exceptions as google_auth_exceptions
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

# Cloud Run はコンテナ起動時に K_SERVICE を自動設定する（ローカルには存在しない）。
# これを使えば、デプロイ時に環境変数を設定し忘れて本番で認証が無効になる、
# という事故を避けられる。
_IS_CLOUD_RUN = "K_SERVICE" in os.environ
_google_request = google_requests.Request()


def _parse_allowed_callers(raw: str) -> frozenset[str]:
    """カンマ区切りのサービスアカウントのメールアドレスを集合にする。"""
    return frozenset(email.strip() for email in raw.split(",") if email.strip())


# トークンの宛先（aud）として受け付ける値。フロントエンドがトークンを発行するときに
# 指定している URL（フロントエンドの BACKEND_URL）と同じ値を設定する。
_AUDIENCE = os.environ.get("AUTH_AUDIENCE", "")

# 呼び出しを許可するサービスアカウント（トークンの発行先 = email）。
_ALLOWED_CALLERS = _parse_allowed_callers(os.environ.get("AUTH_ALLOWED_CALLERS", ""))

# 本番で設定が足りないときは、認証を素通りさせるのではなく起動自体を失敗させる。
# 起動に失敗したリビジョンには Cloud Run がトラフィックを流さないため、
# 設定漏れのまま「誰でも通る」状態になることはない（フェイルクローズ）。
if _IS_CLOUD_RUN and (not _AUDIENCE or not _ALLOWED_CALLERS):
    raise RuntimeError(
        "AUTH_AUDIENCE と AUTH_ALLOWED_CALLERS を環境変数で設定してください"
    )


def verify_token(request: Request) -> None:
    """フロントエンドが送る Google ID トークン（Authorization: Bearer）を検証する。

    次の3点をすべて満たすときだけ通す。
      1. Google が署名した、期限内のトークンである
      2. 宛先（aud）がこのバックエンド（AUTH_AUDIENCE）である
      3. 発行先（email）が許可したサービスアカウント（AUTH_ALLOWED_CALLERS）である

    ローカル実行時は BACKEND_URL の未設定によりフロントエンドがトークンを
    そもそも送らないため、検証をスキップする。
    """
    if not _IS_CLOUD_RUN:
        return

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization ヘッダーがありません")

    token = auth_header.removeprefix("Bearer ")
    try:
        # 1 と 2 を確認する（署名・有効期限・発行元 iss・宛先 aud）。
        claims = id_token.verify_oauth2_token(token, _google_request, audience=_AUDIENCE)
    except (ValueError, google_auth_exceptions.GoogleAuthError):
        # 発行元（iss）が違う場合は ValueError ではなく GoogleAuthError になるため、両方を捕まえる。
        raise HTTPException(status_code=401, detail="トークンが無効です")

    # 3 を確認する。トークン自体は正しくても、許可していない相手なら 403 にする。
    if not claims.get("email_verified") or claims.get("email") not in _ALLOWED_CALLERS:
        raise HTTPException(status_code=403, detail="この呼び出し元は許可されていません")
