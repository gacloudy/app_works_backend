import os
from google.cloud import secretmanager


def get_secret(secret_id: str) -> str:
    """GCP Secret Manager からシークレットの最新バージョンを取得する。

    GCP_PROJECT_ID 環境変数が必須。
    認証はローカルでは GOOGLE_APPLICATION_CREDENTIALS（JSON キー）、
    GCP 上ではインスタンスのサービスアカウントが自動で使われる。
    """
    project_id = os.environ["GCP_PROJECT_ID"]
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")
