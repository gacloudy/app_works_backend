import os

from fastapi import HTTPException, Request
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

# Cloud Run はコンテナ起動時に K_SERVICE を自動設定する（ローカルには存在しない）。
# これを使えば、デプロイ時に環境変数を設定し忘れて本番で認証が無効になる、
# という事故を避けられる。
_IS_CLOUD_RUN = "K_SERVICE" in os.environ
_google_request = google_requests.Request()


def verify_token(request: Request) -> None:
    """フロントエンドが送る Google ID トークン（Authorization: Bearer）を検証する。

    ローカル実行時は BACKEND_URL の未設定によりフロントエンドがトークンを
    そもそも送らないため、検証をスキップする。
    """
    if not _IS_CLOUD_RUN:
        return

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization ヘッダーがありません")

    token = auth_header.removeprefix("Bearer ")
    audience = os.environ.get("BACKEND_URL")
    try:
        id_token.verify_oauth2_token(token, _google_request, audience=audience)
    except ValueError:
        raise HTTPException(status_code=401, detail="トークンが無効です")
